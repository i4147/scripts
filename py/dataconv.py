"""
dataconv.py — convert between CSV / JSON / SQLite (.db) / SQL dump (.sql).

Examples
--------
    python dataconv.py --csv  data.json          # json -> csv
    python dataconv.py --json data.csv           # csv  -> json
    python dataconv.py --db   dump.sql           # sql  -> sqlite
    python dataconv.py --sql  app.db             # db   -> sql dump
    python dataconv.py --csv  a.json b.json c.json -j 4 -o out/

Design
------
* Every loader returns a common in-memory model:
      Tables = {table_name: [ {col: value, ...}, ... ]}
* Every writer consumes that model.
* Files > 5 MB are read through ``mmap`` instead of a normal read.
* Multiple input files are converted in parallel with ``multiprocessing.Pool.map``.
* All failures are reported through loguru.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import mmap
import os
import re
import sqlite3
import sys
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

# --------------------------------------------------------------------------- #
# Types / constants
# --------------------------------------------------------------------------- #

Tables = Dict[str, List[Dict[str, Any]]]

MMAP_THRESHOLD = 1024 * 1024  # 1 MB

EXT_TO_FMT = {
    ".csv": "csv",
    ".tsv": "csv",
    ".json": "json",
    ".db": "db",
    ".sqlite": "db",
    ".sqlite3": "db",
    ".sql": "sql",
}
FMT_TO_EXT = {"csv": ".csv", "json": ".json", "db": ".db", "sql": ".sql"}


# --------------------------------------------------------------------------- #
# Low-level helpers
# --------------------------------------------------------------------------- #


def read_text(path: Path) -> str:
    """Read a text file, memory-mapping it when it is bigger than 5 MB."""
    size = path.stat().st_size
    if size == 0:
        return ""
    if size > MMAP_THRESHOLD:
        logger.debug(f"mmap read: {path} ({size / 1_048_576:.1f} MB)")
        with path.open("rb") as fh:
            with mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                return mm[:].decode("utf-8", errors="replace")
    return path.read_text(encoding="utf-8")


def detect_format(path: Path) -> Optional[str]:
    return EXT_TO_FMT.get(path.suffix.lower())


def _columns(rows: List[Dict[str, Any]]) -> List[str]:
    """Ordered union of keys across all rows."""
    cols: List[str] = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                cols.append(key)
    return cols


def _flat(value: Any) -> Any:
    """Flatten a value for CSV output."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float, str)):
        return value
    return json.dumps(value, ensure_ascii=False)


def _infer_sql_type(values) -> str:
    kind = None
    for v in values:
        if v is None:
            continue
        if isinstance(v, bool) or isinstance(v, int):
            if kind in (None, "INTEGER"):
                kind = "INTEGER"
            elif kind == "REAL":
                kind = "REAL"
            else:
                return "TEXT"
        elif isinstance(v, float):
            if kind in (None, "INTEGER", "REAL"):
                kind = "REAL"
            else:
                return "TEXT"
        else:
            return "TEXT"
    return kind or "TEXT"


def _sqlite_val(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str, bytes)):
        return value
    return json.dumps(value, ensure_ascii=False)


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return "'" + json.dumps(value, ensure_ascii=False).replace("'", "''") + "'"


# --------------------------------------------------------------------------- #
# Loaders  ->  Tables
# --------------------------------------------------------------------------- #


def load_csv(path: Path) -> Tables:
    text = read_text(path)
    reader = csv.DictReader(io.StringIO(text))
    rows = [dict(r) for r in reader]
    return {path.stem: rows}


def load_json(path: Path) -> Tables:
    data = json.loads(read_text(path))
    if isinstance(data, list):
        rows = [r if isinstance(r, dict) else {"value": r} for r in data]
        return {path.stem: rows}
    if isinstance(data, dict):
        # {table: [ {...}, ... ]}  -> multi table
        if data and all(isinstance(v, list) and all(isinstance(x, dict) for x in v) for v in data.values()):
            return {str(k): list(v) for k, v in data.items()}
        # single object -> single row
        return {path.stem: [data]}
    return {path.stem: [{"value": data}]}


def load_db(path: Path) -> Tables:
    size = path.stat().st_size
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        if size > MMAP_THRESHOLD:
            logger.debug(f"sqlite mmap_size for {path} ({size / 1_048_576:.1f} MB)")
            con.execute(f"PRAGMA mmap_size={size}")
        names = [
            r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        ]
        out: Tables = {}
        for name in names:
            out[name] = [dict(r) for r in con.execute(f'SELECT * FROM "{name}"')]
        return out
    finally:
        con.close()


# ---------------------------- SQL dump parsing ----------------------------- #

_CREATE_RE = re.compile(
    r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"\[\]]?(\w+)[`"\[\]]?\s*\(',
    re.I,
)
_INSERT_RE = re.compile(
    r'INSERT\s+(?:OR\s+\w+\s+)?INTO\s+[`"\[\]]?(\w+)[`"\[\]]?\s*'
    r"(?:\(([^)]*)\))?\s*VALUES\s*",
    re.I,
)
_NON_COLUMN_KEYWORDS = {
    "PRIMARY",
    "FOREIGN",
    "UNIQUE",
    "CHECK",
    "CONSTRAINT",
    "KEY",
    "INDEX",
}


def _split_top_level(s: str) -> List[str]:
    parts, cur, depth, in_str, quote = [], [], 0, False, ""
    for ch in s:
        if in_str:
            cur.append(ch)
            if ch == quote:
                in_str = False
        elif ch in "'\"":
            in_str, quote = True, ch
            cur.append(ch)
        elif ch == "(":
            depth += 1
            cur.append(ch)
        elif ch == ")":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return parts


def _iter_create_tables(text: str):
    """Yield (table_name, body) for every CREATE TABLE, honouring nesting."""
    for m in _CREATE_RE.finditer(text):
        name = m.group(1)
        i, depth, start = m.end(), 1, m.end()
        in_str, quote = False, ""
        while i < len(text) and depth:
            c = text[i]
            if in_str:
                if c == "\\":
                    i += 2
                    continue
                if c == quote:
                    in_str = False
            elif c in "'\"":
                in_str, quote = True, c
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            i += 1
        yield name, text[start : i - 1]


def _iter_inserts(text: str):
    """Yield (table, column_list_or_None, raw_values_string)."""
    for m in _INSERT_RE.finditer(text):
        name = m.group(1)
        cols = m.group(2)
        i, depth, start = m.end(), 0, m.end()
        in_str, quote = False, ""
        while i < len(text):
            c = text[i]
            if in_str:
                if c == "\\" and quote == "'":
                    i += 2
                    continue
                if c == quote:
                    if i + 1 < len(text) and text[i + 1] == quote:
                        i += 2
                        continue
                    in_str = False
                i += 1
            elif c in "'\"":
                in_str, quote = True, c
                i += 1
            elif c == "(":
                depth += 1
                i += 1
            elif c == ")":
                depth -= 1
                i += 1
            elif c == ";" and depth == 0:
                break
            else:
                i += 1
        yield name, cols, text[start:i]


def _convert_sql_value(tok: str) -> Any:
    if tok == "":
        return None
    upper = tok.upper()
    if upper == "NULL":
        return None
    if upper == "TRUE":
        return True
    if upper == "FALSE":
        return False
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "'\"":
        quote = tok[0]
        return tok[1:-1].replace(quote + quote, quote)
    try:
        return int(tok)
    except ValueError:
        pass
    try:
        return float(tok)
    except ValueError:
        pass
    return tok


def _parse_value_tuples(raw: str) -> List[List[Any]]:
    """Parse `(1,'a',NULL),(2,'b',NULL)` into python rows."""
    rows: List[List[Any]] = []
    i, n = 0, len(raw)
    while i < n:
        while i < n and raw[i] in " \t\r\n,":
            i += 1
        if i >= n or raw[i] != "(":
            break
        i += 1
        row, cur = [], []
        in_str, quote = False, ""
        while i < n:
            c = raw[i]
            if in_str:
                if c == "\\" and quote == "'" and i + 1 < n:
                    nxt = raw[i + 1]
                    cur.append({"n": "\n", "t": "\t", "r": "\r", "0": "\0"}.get(nxt, nxt))
                    i += 2
                    continue
                if c == quote:
                    if i + 1 < n and raw[i + 1] == quote:
                        cur.append(c)
                        i += 2
                        continue
                    in_str = False
                    cur.append(c)
                    i += 1
                    continue
                cur.append(c)
                i += 1
            else:
                if c in "'\"":
                    in_str, quote = True, c
                    cur.append(c)
                    i += 1
                elif c == ",":
                    row.append("".join(cur).strip())
                    cur = []
                    i += 1
                elif c == ")":
                    row.append("".join(cur).strip())
                    i += 1
                    break
                else:
                    cur.append(c)
                    i += 1
        rows.append([_convert_sql_value(v) for v in row])
    return rows


def load_sql(path: Path) -> Tables:
    text = read_text(path)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"^\s*--.*$", "", text, flags=re.M)
    text = re.sub(r"^\s*#.*$", "", text, flags=re.M)

    tables: Tables = {}
    declared_cols: Dict[str, List[str]] = {}

    for name, body in _iter_create_tables(text):
        cols: List[str] = []
        for part in _split_top_level(body):
            part = part.strip()
            if not part:
                continue
            head = part.split()[0].strip('`"[]')
            if head.upper() in _NON_COLUMN_KEYWORDS:
                continue
            cols.append(head)
        declared_cols[name] = cols
        tables.setdefault(name, [])

    for name, col_list, raw_values in _iter_inserts(text):
        if col_list:
            cols = [c.strip().strip('`"[]') for c in col_list.split(",")]
        else:
            cols = list(declared_cols.get(name, []))

        for values in _parse_value_tuples(raw_values):
            if not cols:
                cols = [f"c{i}" for i in range(len(values))]
                declared_cols[name] = cols
            tables.setdefault(name, []).append(dict(zip(cols, values)))

    return tables


LOADERS = {
    "csv": load_csv,
    "json": load_json,
    "db": load_db,
    "sql": load_sql,
}


# --------------------------------------------------------------------------- #
# Writers  Tables -> file
# --------------------------------------------------------------------------- #


def write_csv(tables: Tables, out_path: Path) -> List[Path]:
    multi = len(tables) > 1
    written: List[Path] = []
    for name, rows in tables.items():
        target = out_path.with_name(f"{out_path.stem}.{name}{out_path.suffix}") if multi else out_path
        cols = _columns(rows)
        with target.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=cols)
            writer.writeheader()
            for row in rows:
                writer.writerow({c: _flat(row.get(c)) for c in cols})
        written.append(target)
    return written


def write_json(tables: Tables, out_path: Path) -> List[Path]:
    payload: Any = next(iter(tables.values())) if len(tables) == 1 else tables
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return [out_path]


def write_db(tables: Tables, out_path: Path) -> List[Path]:
    if out_path.exists():
        out_path.unlink()
    con = sqlite3.connect(out_path)
    try:
        for name, rows in tables.items():
            cols = _columns(rows)
            if not cols:
                logger.warning(f"skipping empty table {name!r}")
                continue
            types = {c: _infer_sql_type([r.get(c) for r in rows]) for c in cols}
            col_defs = ", ".join(f'"{c}" {types[c]}' for c in cols)
            con.execute(f'CREATE TABLE "{name}" ({col_defs})')
            placeholders = ", ".join("?" * len(cols))
            con.executemany(
                f'INSERT INTO "{name}" VALUES ({placeholders})',
                [[_sqlite_val(r.get(c)) for c in cols] for r in rows],
            )
        con.commit()
    finally:
        con.close()
    return [out_path]


def write_sql(tables: Tables, out_path: Path) -> List[Path]:
    lines: List[str] = ["-- generated by dataconv.py", ""]
    for name, rows in tables.items():
        cols = _columns(rows)
        if not cols:
            continue
        types = {c: _infer_sql_type([r.get(c) for r in rows]) for c in cols}
        col_defs = ", ".join(f'"{c}" {types[c]}' for c in cols)
        lines.append(f'CREATE TABLE IF NOT EXISTS "{name}" ({col_defs});')
        col_list = ", ".join(f'"{c}"' for c in cols)
        for row in rows:
            values = ", ".join(_sql_literal(row.get(c)) for c in cols)
            lines.append(f'INSERT INTO "{name}" ({col_list}) VALUES ({values});')
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return [out_path]


WRITERS = {
    "csv": write_csv,
    "json": write_json,
    "db": write_db,
    "sql": write_sql,
}


# --------------------------------------------------------------------------- #
# Job plumbing (must be module level for multiprocessing pickling)
# --------------------------------------------------------------------------- #


def _output_path(src: Path, target_fmt: str, out_dir: Optional[Path]) -> Path:
    name = src.stem + FMT_TO_EXT[target_fmt]
    return (out_dir / name) if out_dir else src.with_name(name)


def convert_job(job: Tuple[str, str, Optional[str]]) -> Tuple[str, bool, List[str], str]:
    """Worker: (source, target_format, output_dir) -> (source, ok, outputs, msg)."""
    src_str, target_fmt, out_dir_str = job
    src = Path(src_str)
    try:
        src_fmt = detect_format(src)
        if src_fmt is None:
            raise ValueError(f"unsupported input extension {src.suffix!r}")
        if src_fmt == target_fmt:
            return src_str, True, [], f"skipped: already {target_fmt}"

        logger.info(f"{src} [{src_fmt}] -> {target_fmt}")
        tables = LOADERS[src_fmt](src)
        if not tables:
            raise ValueError("no tables / rows found in input")

        out_path = _output_path(src, target_fmt, Path(out_dir_str) if out_dir_str else None)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        written = WRITERS[target_fmt](tables, out_path)
        return src_str, True, [str(p) for p in written], "ok"
    except Exception as exc:  # noqa: BLE001 - report everything
        logger.exception(f"failed to convert {src}")
        return src_str, False, [], f"{type(exc).__name__}: {exc}"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dataconv",
        description="Convert between csv / json / sqlite(db) / sql data containers.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--csv", action="store_true", help="write CSV output")
    group.add_argument("--json", action="store_true", help="write JSON output")
    group.add_argument("--db", action="store_true", help="write SQLite output")
    group.add_argument("--sql", action="store_true", help="write SQL dump output")

    parser.add_argument("inputs", nargs="+", type=Path, help="input file(s)")
    parser.add_argument(
        "-o", "--output-dir", type=Path, default=None, help="directory for outputs (default: next to input)"
    )
    parser.add_argument(
        "-j", "--jobs", type=int, default=os.cpu_count() or 1, help="parallel workers for multiple inputs"
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    logger.remove()
    logger.add(sys.stderr, format="<level>{level: <8}</level> | {message}")

    args = parse_args(argv)
    target_fmt = "csv" if args.csv else "json" if args.json else "db" if args.db else "sql"

    sources: List[Path] = []
    for p in args.inputs:
        if not p.exists():
            logger.error(f"input not found: {p}")
            continue
        if not p.is_file():
            logger.error(f"not a file: {p}")
            continue
        sources.append(p)

    if not sources:
        logger.error("no usable inputs")
        return 2

    jobs = [(str(p), target_fmt, str(args.output_dir) if args.output_dir else None) for p in sources]

    if len(jobs) > 1 and args.jobs > 1:
        workers = min(args.jobs, len(jobs))
        logger.info(f"converting {len(jobs)} files with {workers} workers")
        with Pool(processes=workers) as pool:
            results = pool.map(convert_job, jobs, chunksize=1)
    else:
        results = [convert_job(j) for j in jobs]

    failures = 0
    for src, ok, outputs, msg in results:
        if ok:
            if outputs:
                logger.success(f"{src} -> {', '.join(outputs)}")
            elif msg:
                logger.warning(f"{src}: {msg}")
        else:
            failures += 1
            logger.error(f"{src}: {msg}")

    logger.info(f"done: {len(results) - failures} ok, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
