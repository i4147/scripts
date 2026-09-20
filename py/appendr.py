from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dh import mpf3

CWD = Path.cwd().resolve()
TOOLS = ("ty", "ruff", "pyright", "pylint")

ENABLED_TOOLS: frozenset[str] = frozenset({"ty"})

IGNORED_FALSE_POSITIVE_IMPORTS = {"dh"}

MAX_OUTPUT_CHARS = 200_000
COMMAND_TIMEOUT = 120

EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".pyright",
    "site-packages",
}


@dataclass
class ToolResult:
    count: int = 0
    text: str = ""
    status: str = "ok"


def _ansi_strip(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _truncate(text: str) -> str:
    text = text.strip()
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS].rstrip() + "\n...[output truncated]"


def _run_cmd(cmd: list[str], timeout: int = COMMAND_TIMEOUT) -> tuple[int | None, str]:
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    env["COLUMNS"] = "200"

    try:
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=CWD,
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        partial = _ansi_strip(partial)
        return -1, _truncate(partial + f"\n[command timed out: {' '.join(cmd)}]")
    except OSError as exc:
        return None, f"failed to run {' '.join(cmd)}: {exc}"

    return proc.returncode, _truncate(_ansi_strip(proc.stdout or ""))


def _rel(path: Path) -> str:
    path = Path(path).resolve()
    try:
        return str(path.relative_to(CWD))
    except ValueError:
        return str(path)


def _is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.parent.parts)


def _collect_py_files(raw_paths: list[str]) -> list[Path]:
    roots = [Path(p).expanduser() for p in raw_paths] if raw_paths else [CWD]
    found: set[Path] = set()

    for root in roots:
        try:
            root = Path(root).resolve()
        except (OSError, RuntimeError) as exc:
            print(f"warning: skipping bad path {root}: {exc}", file=sys.stderr)
            continue

        if root.is_file():
            if root.suffix == ".py" and not _is_excluded(root):
                found.add(root)
            continue

        try:
            iterator = root.rglob("*.py")
            for py in iterator:
                if not py.is_file():
                    continue
                try:
                    py = py.resolve()
                except (OSError, RuntimeError):
                    continue
                if not _is_excluded(py):
                    found.add(py)
        except OSError as exc:
            print(f"warning: error walking {root}: {exc}", file=sys.stderr)

    return sorted(found, key=lambda p: p.as_posix())


def _ty_diag_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if re.match(r"^(?:error|warning)\[", line))


def _filter_ty_unresolved_imports(text: str) -> str:
    if not text.strip():
        return ""

    blocks = re.split(r"(?=^(?:error|warning)\[)", text, flags=re.M)
    kept: list[str] = []

    for block in blocks:
        header = "".join(block.splitlines(keepends=True)).strip().splitlines()
        first_line = header[0].strip() if header else ""

        is_unresolved = bool(re.match(r"^(?:error|warning)\[unresolved-import\]", first_line))

        if is_unresolved:
            lowered = block.lower()
            if any(re.search(rf"\b{re.escape(mod)}\b", lowered) for mod in IGNORED_FALSE_POSITIVE_IMPORTS):
                continue

        kept.append(block)

    filtered = "".join(kept).strip()
    count = _ty_diag_count(filtered)
    if not count:
        return ""

    filtered = re.sub(
        r"(?im)^Found\s+\d+\s+diagnostics?\s*$",
        f"Found {count} diagnostic" + ("s" if count != 1 else ""),
        filtered,
    )
    return _truncate(filtered)


def run_ty(path: Path) -> ToolResult:
    code, output = _run_cmd(["ty", "check", _rel(path)])
    if code is None:
        return ToolResult(status="missing", text=output)
    if code == -1:
        return ToolResult(status="timeout", text=output)

    filtered = _filter_ty_unresolved_imports(output)
    count = _ty_diag_count(filtered)
    return ToolResult(count=count, text=filtered if count else "")


def run_ruff(path: Path) -> ToolResult:
    code, output = _run_cmd(["ruff", "check", "--fix", "--unsafe-fixes", "--diff", _rel(path)])
    if code is None:
        return ToolResult(status="missing", text=output)
    if code == -1:
        return ToolResult(status="timeout", text=output)

    if not output.strip() or code == 0:
        return ToolResult(count=0)
    return ToolResult(count=1, text=output)


def run_pyright(path: Path) -> ToolResult:
    code, output = _run_cmd(["pyright", _rel(path)])
    if code is None:
        return ToolResult(status="missing", text=output)
    if code == -1:
        return ToolResult(status="timeout", text=output)

    if not output.strip():
        return ToolResult(count=0)

    errors = len(re.findall(r" - error: ", output))
    warnings = len(re.findall(r" - warning: ", output))

    summary = re.search(r"(\d+)\s+errors?,\s*(\d+)\s+warnings?", output, re.I)
    if summary:
        errors = max(errors, int(summary.group(1)))
        warnings = max(warnings, int(summary.group(2)))

    count = errors + warnings
    return ToolResult(count=count, text=output if count else "")


def run_pylint(path: Path) -> ToolResult:
    path = Path(path)
    code, output = _run_cmd(["pylint", _rel(str(path))])
    if code is None:
        return ToolResult(status="missing", text=output)
    if code == -1:
        return ToolResult(status="timeout", text=output)

    if not output.strip():
        return ToolResult(count=0)

    count = 0
    for line in output.splitlines():
        if re.search(r":\d+:\d+: [A-Z]\d+:", line):
            count += 1

    return ToolResult(count=count, text=output if count else "")


_TOOL_RUNNERS = {
    "ty": run_ty,
    "ruff": run_ruff,
    "pyright": run_pyright,
    "pylint": run_pylint,
}


def _append_tool_output(path: Path, tool: str, output: str) -> None:
    path = Path(path)
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    rel = _rel(path)

    lines = []
    for line in output.rstrip("\n").splitlines():
        lines.append(f"# {line.rstrip()}" if line.strip() else "#")

    block = "\n".join(
        [
            f"# --- {tool} {rel} @ {timestamp} ---",
            *lines,
            f"# --- end {tool} ---",
            "",
        ]
    ).encode("utf-8")

    with Path(path).open("ab") as fh:
        fh.seek(0, os.SEEK_END)
        if fh.tell() > 0:
            fh.seek(-1, os.SEEK_END)
            if fh.read(1) != b"\n":
                fh.write(b"\n")
        fh.write(block)


def process_file(path: Path) -> tuple[Path, dict[str, object]]:
    path = Path(path)
    stats: dict[str, object] = {tool: None for tool in TOOLS}
    stats["error"] = ""

    for tool in TOOLS:
        if tool not in ENABLED_TOOLS:
            continue

        if shutil.which(tool) is None:
            stats[tool] = ToolResult(status="missing")
            continue

        try:
            result = _TOOL_RUNNERS[tool](path)
        except Exception as exc:
            stats[tool] = ToolResult(status="error", text=str(exc))
            stats["error"] = f"{tool} error: {exc}"
            continue

        stats[tool] = result

        if result.status in {"error", "timeout"}:
            stats["error"] = f"{tool} {result.status}: {result.text[:200]}"
            continue

        if result.status == "ok" and result.count > 0 and result.text:
            try:
                _append_tool_output(path, tool, result.text)
            except Exception as exc:
                stats["error"] = f"failed appending {tool} to {_rel(path)}: {exc}"

    return path, stats


def print_results(files: list[Path], results: list[tuple[Path, dict[str, object]]]) -> None:
    result_map = {str(Path(p).resolve()): stats for p, stats in results}

    print("\n=== per-file results ===")

    for path in files:
        stats = result_map.get(str(Path(path).resolve()), {})
        rel = _rel(path)
        bits = []

        for tool in TOOLS:
            if tool not in ENABLED_TOOLS:
                continue

            result = stats.get(tool)
            if result is None:
                bits.append(f"{tool}=SKIP")
            elif isinstance(result, ToolResult):
                if result.status != "ok":
                    bits.append(f"{tool}={result.status.upper()}")
                else:
                    bits.append(f"{tool}={result.count}")

        err = stats.get("error")
        if err:
            bits.append(f"error={err}")

        print(f"{rel}: " + ", ".join(bits))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ty (and optionally ruff/pyright/pylint) and append diagnostics.")
    parser.add_argument("paths", nargs="*", help="files or directories; defaults to current dir")
    parser.add_argument("-r", "--ruff", action="store_true", help="also run ruff")
    parser.add_argument("-g", "--pyright", action="store_true", help="also run pyright")
    parser.add_argument("-p", "--pylint", action="store_true", help="also run pylint")
    parser.add_argument("-a", "--all", action="store_true", help="run all tools")
    parser.add_argument("--no-ty", action="store_true", help="disable ty (default tool)")

    args = parser.parse_args()

    enabled = {"ty"}
    if args.all:
        enabled.update(TOOLS)
    if args.ruff:
        enabled.add("ruff")
    if args.pyright:
        enabled.add("pyright")
    if args.pylint:
        enabled.add("pylint")
    if args.no_ty and not args.all:
        enabled.discard("ty")
    elif args.no_ty:
        enabled.discard("ty")

    if not enabled:
        print("No tools selected; aborting.", file=sys.stderr)
        return 1

    files = _collect_py_files(args.paths)
    if not files:
        print("No .py files found.", file=sys.stderr)
        return 0

    global ENABLED_TOOLS
    ENABLED_TOOLS = frozenset(enabled)

    print(f"running: {', '.join(sorted(ENABLED_TOOLS))} on {len(files)} file(s)")

    try:
        results: list[tuple[Path, dict[str, object]]] = list(mpf3(process_file, files))
    except Exception as exc:
        print(f"parallel worker failed ({exc}); falling back to sequential", file=sys.stderr)
        results = [process_file(f) for f in files]

    print_results(files, results)
    print(f"\ncompleted {len(files)} file(s)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
