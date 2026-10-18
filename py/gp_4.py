from __future__ import annotations
import argparse
import ast
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from dulwich import porcelain
from dulwich.errors import GitProtocolError, NotGitRepository
from dulwich.repo import Repo

SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "build",
    "dist",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Auto-commit and push the current git repository.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--format",
        dest="format",
        action="store_true",
        default=False,
        help="Run `ruff format` on all .py files before committing.",
    )
    parser.add_argument(
        "--validate",
        dest="validate",
        action="store_true",
        default=False,
        help="Parse all .py files with `ast.parse` before committing.",
    )
    return parser.parse_args(argv)


def copy_global_gitignore() -> None:
    home_gitignore = Path.home() / ".gitignore"
    local_gitignore = Path(".gitignore")
    if local_gitignore.exists():
        return
    try:
        data = home_gitignore.read_text(encoding="utf-8")
        local_gitignore.write_text(data, encoding="utf-8")
    except Exception:
        return


def open_repo() -> Repo:
    try:
        return Repo.discover(".")
    except NotGitRepository:
        print("Error: Not a git repository.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error accessing repository: {e}", file=sys.stderr)
        sys.exit(1)


def active_branch_name(repo: Repo) -> str:
    try:
        return porcelain.active_branch(repo)
    except (ValueError, KeyError):
        print(
            "Error: Could not detect current branch (detached HEAD?).",
            file=sys.stderr,
        )
        sys.exit(1)


def find_python_files(repo: Repo) -> list[Path]:
    root = Path(repo.path)
    seen: set[Path] = set()
    py_files: list[Path] = []

    def _add(path: Path) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            return
        if resolved in seen or not resolved.is_file():
            return
        if resolved.suffix != ".py":
            return
        seen.add(resolved)
        py_files.append(resolved)

    try:
        for entry in repo.open_index().items():
            _add(root / entry.path.decode("utf-8", "surrogateescape"))
    except Exception as e:
        print(f"Warning: could not read index: {e}", file=sys.stderr)
    for path in root.rglob("*.py"):
        parts = path.relative_to(root).parts
        if any(p in SKIP_DIR_NAMES or p.endswith(".egg-info") for p in parts):
            continue
        _add(path)
    py_files.sort()
    return py_files


def run_ruff_format(files: list[Path]) -> None:
    ruff = shutil.which("ruff")
    if ruff is None:
        print(
            "Warning: ruff not found on PATH; skipping formatting.",
            file=sys.stderr,
        )
        return
    if not files:
        print("ruff format: no .py files to format.")
        return
    result = subprocess.run(
        [ruff, "format", *[str(f) for f in files]],
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0:
        print("ruff format failed:", file=sys.stderr)
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        sys.exit(result.returncode)


def validate_python_syntax(files: list[Path]) -> None:
    if not files:
        print("Syntax validation: no .py files found.")
        return
    failures: list[tuple[Path, BaseException]] = []
    for path in files:
        try:
            source = path.read_text(encoding="utf-8")
            ast.parse(source, filename=str(path))
        except SyntaxError as e:
            failures.append((path, e))
        except Exception as e:
            failures.append((path, e))
    if not failures:
        print(f"Syntax validation: OK ({len(files)} file(s) parsed).")
        return
    print(
        f"Syntax validation: FAILED ({len(failures)} of {len(files)} file(s)).",
        file=sys.stderr,
    )
    for path, err in failures:
        if isinstance(err, SyntaxError):
            print(
                f"  {path}:{err.lineno}:{err.offset}: {err.msg}",
                file=sys.stderr,
            )
        else:
            print(f"  {path}: {err}", file=sys.stderr)
    sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    repo = open_repo()
    copy_global_gitignore()
    try:
        py_files: list[Path] = []
        if args.format or args.validate:
            py_files = find_python_files(repo)
        if args.format:
            run_ruff_format(py_files)
        else:
            print("Skipping ruff format (--format not given).")
        if args.validate:
            validate_python_syntax(py_files)
        else:
            print("Skipping syntax validation (--validate not given).")
        porcelain.add(repo, [b"."])
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        commit_msg = f"Auto-commit at {now}"
        porcelain.commit(repo, commit_msg.encode("utf-8"))
        branch = active_branch_name(repo)
        porcelain.push(
            repo,
            "origin",
            f"refs/heads/{branch}:refs/heads/{branch}",
        )
        print(f"Pushed to origin/{branch} with message: {commit_msg}")
    except GitProtocolError as e:
        print(f"Git command error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
