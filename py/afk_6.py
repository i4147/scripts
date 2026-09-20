
import argparse
import ast
import multiprocessing
import shutil
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class UnusedImport:
    lineno: int
    col_offset: int
    statement: str
    names: list[str]


@dataclass
class FileReport:
    path: str
    unused: list[UnusedImport] = field(default_factory=list)
    error: Optional[str] = None


def _dotted(name: str, asname: Optional[str]) -> tuple[str, str]:
    bound = asname if asname else name.split(".")[0]
    full = asname if asname else name
    return bound, full


def _collect_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            root = child
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name):
                names.add(root.id)
    return names


def _collect_string_uses(tree: ast.AST) -> set[str]:
    tokens: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for tok in node.value.replace(",", " ").split():
                tok = tok.strip("'\"()[] ")
                if tok.isidentifier():
                    tokens.add(tok)
    return tokens


def _is_under_type_checking(node: ast.AST, tree: ast.AST) -> bool:
    parent: dict[int, ast.AST] = {}
    for p in ast.walk(tree):
        for child in ast.iter_child_nodes(p):
            parent[id(child)] = p
    current = parent.get(id(node))
    while current is not None:
        if isinstance(current, ast.If):
            test = current.test
            if (
                isinstance(test, ast.Name)
                and test.id == "TYPE_CHECKING"
                or isinstance(test, ast.Attribute)
                and test.attr == "TYPE_CHECKING"
            ):
                return True
        current = parent.get(id(current))
    return False


def analyse_source(source: str, display_path: str) -> FileReport:
    report = FileReport(path=display_path)
    try:
        tree = ast.parse(source, filename=display_path)
    except SyntaxError as exc:
        report.error = f"SyntaxError: {exc}"
        return report
    lines = source.splitlines()
    used_names: set[str] = set()
    import_nodes: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            import_nodes.append(node)
        else:
            used_names |= _collect_names(node)
    used_names |= _collect_string_uses(tree)
    for node in import_nodes:
        if _is_under_type_checking(node, tree):
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue
        unused_names: list[str] = []
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound, _ = _dotted(alias.name, alias.asname)
                if bound not in used_names:
                    unused_names.append(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    break
                bound, _ = _dotted(alias.name, alias.asname)
                if bound not in used_names:
                    unused_names.append(alias.asname or alias.name)
        if unused_names:
            raw_line = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
            report.unused.append(
                UnusedImport(
                    lineno=node.lineno, col_offset=node.col_offset, statement=raw_line.strip(), names=unused_names
                )
            )
    return report


def _remove_names_from_import(line: str, names_to_remove: set[str]) -> Optional[str]:
    stripped = line.strip()
    if stripped.startswith("import ") and not stripped.startswith("from "):
        parts = stripped[len("import ") :].split(",")
        kept = []
        for part in parts:
            part = part.strip()
            alias_name = part.split()[-1] if " as " in part else part.split(".")[0]
            full_name = part.split(" as ")[0].strip() if " as " in part else part
            remove_key = part.split(" as ")[1].strip() if " as " in part else full_name
            if remove_key not in names_to_remove and alias_name not in names_to_remove:
                kept.append(part)
        if not kept:
            return None
        indent = line[: len(line) - len(line.lstrip())]
        return indent + "import " + ", ".join(kept) + "\n"
    if stripped.startswith("from ") and " import " in stripped:
        prefix, import_part = stripped.split(" import ", 1)
        import_part = import_part.strip().strip("()")
        parts = import_part.split(",")
        kept = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            alias_name = part.split()[-1] if " as " in part else part
            remove_key = part.split(" as ")[1].strip() if " as " in part else part
            if remove_key not in names_to_remove and alias_name not in names_to_remove:
                kept.append(part)
        if not kept:
            return None
        indent = line[: len(line) - len(line.lstrip())]
        return indent + prefix + " import " + ", ".join(kept) + "\n"
    return line


def fix_source(source: str, report: FileReport) -> Optional[str]:
    if not report.unused:
        return None
    lines = source.splitlines(keepends=True)
    removals: dict[int, set[str]] = {}
    for ui in report.unused:
        removals.setdefault(ui.lineno, set()).update(ui.names)
    new_lines: list[str] = []
    for idx, line in enumerate(lines, start=1):
        if idx in removals:
            replacement = _remove_names_from_import(line, removals[idx])
            if replacement is None:
                continue
            new_lines.append(replacement)
        else:
            new_lines.append(line)
    return "".join(new_lines)


def _process_file(args: tuple) -> FileReport:
    path_str, display_path = args
    try:
        source = Path(path_str).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return FileReport(path=display_path, error=str(exc))
    return analyse_source(source, display_path)


def _process_source_tuple(args: tuple) -> FileReport:
    source, display_path = args
    return analyse_source(source, display_path)


def _extract_py_from_whl(archive: Path) -> list[tuple[str, str]]:
    results = []
    try:
        with zipfile.ZipFile(archive) as zf:
            for name in zf.namelist():
                if name.endswith(".py"):
                    try:
                        source = zf.read(name).decode("utf-8", errors="replace")
                        results.append((source, f"{archive}::{name}"))
                    except Exception:
                        pass
    except zipfile.BadZipFile as exc:
        results.append(("", f"{archive}::ERROR:{exc}"))
    return results


def _extract_py_from_tar_zst(archive: Path) -> list[tuple[str, str]]:
    results = []
    try:
        import zstandard

        with archive.open("rb") as fh:
            dctx = zstandard.ZstdDecompressor()
            with tempfile.TemporaryFile() as tmp:
                dctx.copy_stream(fh, tmp)
                tmp.seek(0)
                with tarfile.open(fileobj=tmp) as tf:
                    for member in tf.getmembers():
                        if member.name.endswith(".py") and member.isfile():
                            try:
                                f = tf.extractfile(member)
                                if f:
                                    source = f.read().decode("utf-8", errors="replace")
                                    results.append((source, f"{archive}::{member.name}"))
                            except Exception:
                                pass
    except ImportError:
        try:
            with tarfile.open(archive, "r:zst") as tf:
                for member in tf.getmembers():
                    if member.name.endswith(".py") and member.isfile():
                        try:
                            f = tf.extractfile(member)
                            if f:
                                source = f.read().decode("utf-8", errors="replace")
                                results.append((source, f"{archive}::{member.name}"))
                        except Exception:
                            pass
        except Exception as exc:
            results.append(("", f"{archive}::ERROR:{exc}"))
    except Exception as exc:
        results.append(("", f"{archive}::ERROR:{exc}"))
    return results


RESET = "\x1b[0m"
BOLD = "\x1b[1m"
YELLOW = "\x1b[33m"
RED = "\x1b[31m"
CYAN = "\x1b[36m"
GREEN = "\x1b[32m"


def _coloured(text: str, code: str, use_colour: bool) -> str:
    return f"{code}{text}{RESET}" if use_colour else text


def print_report(reports: list[FileReport], verbose: bool, use_colour: bool) -> int:
    total = 0
    files_with_issues: list[FileReport] = [r for r in reports if r.unused or r.error]
    if not files_with_issues:
        print(_coloured("✓ No unused imports found.", GREEN, use_colour))
        return 0
    for report in files_with_issues:
        if report.error:
            print(_coloured(f"ERROR  {report.path}: {report.error}", RED, use_colour))
            continue
        first = True
        for ui in report.unused:
            total += 1
            label = _coloured(report.path, BOLD, use_colour) if first else " " * len(report.path)
            lineno_str = _coloured(f"line {ui.lineno:>4}", CYAN, use_colour)
            stmt_str = _coloured(ui.statement, YELLOW, use_colour)
            names_note = ""
            if verbose and len(ui.names) < len(ui.statement.split(",")):
                names_note = "  [unused: " + _coloured(", ".join(ui.names), RED, use_colour) + "]"
            print(f"{label}  -->  {lineno_str}  {stmt_str}{names_note}")
            first = False
    print()
    print(_coloured(f"Found {total} unused import(s) across {len(files_with_issues)} file(s).", BOLD, use_colour))
    return total


def collect_tasks(paths: list[Path]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    file_tasks: list[tuple[str, str]] = []
    source_tasks: list[tuple[str, str]] = []

    for path in paths:
        if path.is_file():
            
            suffix = path.suffix.lower()
            name = path.name.lower()
            if suffix == ".py":
                file_tasks.append((str(path), str(path)))
            elif suffix == ".whl":
                source_tasks.extend(_extract_py_from_whl(path))
            elif name.endswith(".tar.zst"):
                source_tasks.extend(_extract_py_from_tar_zst(path))
            
        elif path.is_dir():
            
            for p in path.rglob("*"):
                if not p.is_file():
                    continue
                suffix = p.suffix.lower()
                name = p.name.lower()
                if suffix == ".py":
                    file_tasks.append((str(p), str(p)))
                elif suffix == ".whl":
                    source_tasks.extend(_extract_py_from_whl(p))
                elif name.endswith(".tar.zst"):
                    source_tasks.extend(_extract_py_from_tar_zst(p))
        else:
            
            print(f"Warning: '{path}' does not exist, skipping.", file=sys.stderr)

    return file_tasks, source_tasks


def run(paths: list[Path], workers: int, autofix: bool, dry_run: bool, verbose: bool) -> int:
    use_colour = sys.stdout.isatty()
    if verbose:
        print(f"Scanning {len(paths)} path(s) with {workers} worker(s) …\n")

    file_tasks, source_tasks = collect_tasks(paths)

    if verbose:
        print(f"  {len(file_tasks)} .py file(s), {len(source_tasks)} archive member(s) queued.\n")

    reports: list[FileReport] = []
    with multiprocessing.Pool(processes=workers) as pool:
        if file_tasks:
            reports.extend(pool.map(_process_file, file_tasks))
        if source_tasks:
            reports.extend(pool.map(_process_source_tuple, source_tasks))

    reports.sort(key=lambda r: r.path)
    total = print_report(reports, verbose=verbose, use_colour=use_colour)

    if autofix and total > 0:
        fixed_count = 0
        for report in reports:
            if not report.unused or report.error:
                continue
            if "::" in report.path:
                if verbose:
                    print(f"  skip autofix for archive member: {report.path}")
                continue
            p = Path(report.path)
            try:
                source = p.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                print(f"  cannot read {p}: {exc}", file=sys.stderr)
                continue
            new_source = fix_source(source, report)
            if new_source is None:
                continue
            try:
                ast.parse(new_source, filename=str(p))
            except SyntaxError as exc:
                print(
                    f"  {_coloured('SKIP', RED, use_colour)} autofix on {p} — result failed to parse: {exc}",
                    file=sys.stderr,
                )
                continue
            if dry_run:
                print(f"  {_coloured('[dry-run]', CYAN, use_colour)} would fix {p}")
                fixed_count += 1
                continue
            bak = p.with_suffix(p.suffix + ".bak")
            shutil.copy2(p, bak)
            p.write_text(new_source, encoding="utf-8")
            fixed_count += 1
            if verbose:
                print(f"  {_coloured('fixed', GREEN, use_colour)} {p}  (backup → {bak})")
        action = "would fix" if dry_run else "fixed"
        print(f"\n{action.capitalize()} {fixed_count} file(s).")
    elif dry_run and total == 0:
        print("Nothing to fix.")

    return 1 if total > 0 else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report (and optionally remove) unused imports in Python files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # scan current directory
  %(prog)s src/                     # scan a specific directory
  %(prog)s file1.py file2.py        # scan specific files
  %(prog)s src/ tests/              # scan multiple directories
  %(prog)s file.py src/             # mix files and directories
  %(prog)s -a                       # autofix in-place (with .bak)
  %(prog)s -a --dry-run             # preview fixes without writing
  %(prog)s -v --workers 4           # verbose output, 4 workers
""",
    )
    parser.add_argument(
        "paths", nargs="*", default=["."], help="Files and/or directories to scan (default: current directory)"
    )
    parser.add_argument(
        "-a", "--autofix", action="store_true", help="Remove unused imports in-place; creates .bak backups"
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be changed without writing files")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print extra progress and per-name details")
    parser.add_argument(
        "--workers", type=int, default=8, metavar="N", help="Number of parallel worker processes (default: 8)"
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    
    paths = [Path(p).resolve() for p in args.paths]

    
    valid_paths = []
    for p in paths:
        if p.exists():
            valid_paths.append(p)
        else:
            print(f"Warning: '{p}' does not exist, skipping.", file=sys.stderr)

    if not valid_paths:
        parser.error("No valid files or directories to scan.")

    if args.dry_run and not args.autofix:
        args.autofix = True

    sys.exit(
        run(
            paths=valid_paths,
            workers=max(1, args.workers),
            autofix=args.autofix,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )
    )


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
