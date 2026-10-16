import argparse
import re
import sys
from dataclasses import dataclass, field
from multiprocessing import Pool, cpu_count
from pathlib import Path

IMPORT_RE = re.compile(
    r"""^(?P<indent>\s*)(?P<stmt>(?:import\s+pkg_resources|from\s+pkg_resources\s+import\s+(?P<names>[^\n#]+)))\s*(?P<comment>#.*)?$""",
    re.VERBOSE,
)

USAGE_PATTERNS: list[tuple[re.Pattern, str, bool, bool]] = [
    (
        re.compile(r"pkg_resources\.get_distribution\(\s*([^)]+?)\s*\)\.version"),
        r"importlib.metadata.version(\1)",
        True,
        False,
    ),
    (
        re.compile(r"pkg_resources\.get_distribution\(\s*([^)]+?)\s*\)"),
        r"importlib.metadata.distribution(\1)",
        True,
        False,
    ),
    (
        re.compile(r"pkg_resources\.resource_string\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)"),
        r"importlib.resources.files(\1).joinpath(\2).read_bytes()",
        False,
        True,
    ),
    (
        re.compile(r"pkg_resources\.resource_text\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)"),
        r"importlib.resources.files(\1).joinpath(\2).read_text(encoding='utf-8')",
        False,
        True,
    ),
    (
        re.compile(r"pkg_resources\.resource_filename\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)"),
        r"str(importlib.resources.files(\1).joinpath(\2))",
        False,
        True,
    ),
    (
        re.compile(r"pkg_resources\.resource_stream\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)"),
        r"importlib.resources.files(\1).joinpath(\2).open('rb')",
        False,
        True,
    ),
    (
        re.compile(r"pkg_resources\.require\(\s*([^)]+?)\s*\)"),
        r"importlib.metadata.requires(\1)",
        True,
        False,
    ),
    (
        re.compile(r"pkg_resources\.DistributionNotFound"),
        r"importlib.metadata.PackageNotFoundError",
        True,
        False,
    ),
]

GENERIC_USAGE_RE = re.compile(r"pkg_resources\.([A-Za-z_][A-Za-z0-9_]*)")


@dataclass
class Finding:
    path: Path
    lineno: int
    col: int
    line: str
    kind: str
    pattern: str = ""
    autofixable: bool = False


@dataclass
class FileReport:
    path: Path
    findings: list[Finding] = field(default_factory=list)
    needs_metadata: bool = False
    needs_resources: bool = False
    has_pkg_resources_import: bool = False

    @property
    def has_findings(self) -> bool:
        return bool(self.findings)


def scan_file(path: Path) -> FileReport:
    report = FileReport(path=path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        report.findings.append(
            Finding(
                path=path,
                lineno=0,
                col=0,
                line=f"<unreadable: {exc}>",
                kind="usage_unknown",
                pattern="",
                autofixable=False,
            )
        )
        return report

    lines = text.splitlines()

    for i, line in enumerate(lines, start=1):
        stripped = line.rstrip("\n")

        m_import = IMPORT_RE.match(stripped)
        if m_import:
            report.has_pkg_resources_import = True
            report.findings.append(
                Finding(
                    path=path,
                    lineno=i,
                    col=m_import.start("stmt") + 1,
                    line=stripped,
                    kind="import",
                    pattern=m_import.group("stmt"),
                    autofixable=True,
                )
            )
            continue

        known_matches: list[tuple[int, int]] = []

        for pat, _repl, needs_meta, needs_res in USAGE_PATTERNS:
            for m in pat.finditer(stripped):
                report.findings.append(
                    Finding(
                        path=path,
                        lineno=i,
                        col=m.start() + 1,
                        line=stripped,
                        kind="usage_known",
                        pattern=m.group(0),
                        autofixable=True,
                    )
                )
                known_matches.append((m.start(), m.end()))
                report.needs_metadata = report.needs_metadata or needs_meta
                report.needs_resources = report.needs_resources or needs_res

        for m in GENERIC_USAGE_RE.finditer(stripped):
            is_duplicate = any(m.start() >= start and m.end() <= end for start, end in known_matches)
            if not is_duplicate:
                report.findings.append(
                    Finding(
                        path=path,
                        lineno=i,
                        col=m.start() + 1,
                        line=stripped,
                        kind="usage_unknown",
                        pattern=m.group(0),
                        autofixable=False,
                    )
                )

    return report


def autofix_file(path: Path) -> tuple[bool, list[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False, [f"cannot read {path}"]

    original = text
    notes: list[str] = []

    needs_metadata = False
    needs_resources = False

    for pat, repl, needs_meta, needs_res in USAGE_PATTERNS:
        new_text, n = pat.subn(repl, text)
        if n:
            notes.append(f"replaced {n} occurrence(s) of {pat.pattern!r}")
            needs_metadata = needs_metadata or needs_meta
            needs_resources = needs_resources or needs_res
            text = new_text

    lines = text.splitlines(keepends=True)
    new_lines: list[str] = []
    removed_import = False
    skipped_alias = False

    for line in lines:
        m = IMPORT_RE.match(line.rstrip("\n"))
        if not m:
            new_lines.append(line)
            continue

        stmt = m.group("stmt")
        if re.search(r"\bas\s+\w+\b", stmt) or (
            stmt.startswith("from") and m.group("names") and re.search(r"\bas\s+\w+\b", m.group("names"))
        ):
            skipped_alias = True
            new_lines.append(line)
            continue

        removed_import = True
        notes.append(f"removed import: {stmt.strip()}")

    text = "".join(new_lines)

    if removed_import or needs_metadata or needs_resources:
        insertion_lines: list[str] = []
        if needs_metadata:
            insertion_lines.append("import importlib.metadata\n")
        if needs_resources:
            insertion_lines.append("import importlib.resources\n")
        if insertion_lines:
            text = "".join(insertion_lines) + text
            notes.append("added importlib.metadata / importlib.resources imports")

    if skipped_alias:
        notes.append("WARNING: aliased pkg_resources import left untouched; manual review required")

    if text == original:
        return False, notes

    try:
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        return False, [f"cannot write {path}: {exc}"]

    return True, notes


def iter_python_files(root: Path):
    skipped_dirs = {".git", "__pycache__", ".venv", "venv", "env", ".tox", "build", "dist", ".eggs"}
    for p in root.rglob("*.py"):
        if any(part in skipped_dirs for part in p.parts):
            continue
        if p.is_file():
            yield p


def process_file(args: tuple[Path, str]) -> tuple[Path, FileReport | tuple[bool, list[str]] | None]:
    path, action = args
    if action == "scan":
        return path, scan_file(path)
    elif action == "fix":
        return path, autofix_file(path)
    return path, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report (and optionally autofix) deprecated pkg_resources usage in .py files."
    )
    parser.add_argument("-a", "--autofix", action="store_true", help="Apply mechanical autofixes.")
    parser.add_argument(
        "-w",
        "--max-workers",
        type=int,
        default=8,
        help="Number of parallel workers (default: 8).",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress per-file output.")
    args = parser.parse_args(argv)

    if sys.version_info < (3, 12):
        print(
            f"warning: running on Python {sys.version.split()[0]}; pkg_resources is deprecated in Python 3.12+.",
            file=sys.stderr,
        )

    root = Path.cwd()
    files = list(iter_python_files(root))
    if not files:
        print("no .py files found")
        return 0

    max_workers = max(1, min(args.max_workers, cpu_count()))
    total_findings = 0
    files_with_findings = 0
    autofixed_files = 0

    reports: list[FileReport] = []

    with Pool(processes=max_workers) as pool:
        results = pool.map(process_file, [(p, "scan") for p in files])

        for path, rep in results:
            if isinstance(rep, FileReport):
                reports.append(rep)

    reports.sort(key=lambda r: r.path)

    for rep in reports:
        if not rep.has_findings:
            continue
        files_with_findings += 1
        if not args.quiet:
            print(f"\n== {rep.path} ==")
        for f in rep.findings:
            total_findings += 1
            tag = "AUTOFIX" if f.autofixable else "MANUAL"
            if not args.quiet:
                print(f"  {f.lineno}:{f.col}  [{tag}] ({f.kind})  {f.pattern!r}")
                print(f"      | {f.line.strip()}")

    print()
    print(f"scanned files      : {len(files)}")
    print(f"files with findings: {files_with_findings}")
    print(f"total findings     : {total_findings}")

    if args.autofix:
        print("\n--autofix enabled--")
        files_to_fix = [r.path for r in reports if r.has_findings]

        with Pool(processes=max_workers) as pool:
            results = pool.map(process_file, [(p, "fix") for p in files_to_fix])

            for path, result in results:
                if result is None:
                    continue
                changed, notes = result
                if changed:
                    autofixed_files += 1
                    print(f"  fixed: {path}")
                    for n in notes:
                        print(f"      - {n}")
                else:
                    if notes:
                        print(f"  no-op: {path}")
                        for n in notes:
                            print(f"      - {n}")

        print(f"files autofixed    : {autofixed_files}")

    if total_findings > 0 and not args.autofix:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
