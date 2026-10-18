import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Final
from dotenv import load_dotenv

ENV_PATH: Final[Path] = Path.home() / ".env"
"""Location of the .env file that holds GITHUB_TOKEN."""
GITHUB_API: Final[str] = "https://api.github.com"
"""Base URL for the GitHub REST API."""
DEFAULT_BRANCH: Final[str] = "main"
"""Branch name used for the initial commit and remote tracking."""
VERSION: Final[str] = "1.4.7"
"""Version stamped into pyproject.toml and __init__.py / <pkgname>.py."""
load_dotenv(dotenv_path=ENV_PATH)
GITIGNORE: Final[str] = """\
__pycache__/
*.py[codz]
*$py.class
*.so
build/
dist/
eggs/
.eggs/
*.egg-info/
*.egg
MANIFEST
htmlcov/
.tox/
.nox/
.coverage
.coverage.*
coverage.xml
.hypothesis/
.pytest_cache/
.env
.envrc
.venv
uv.lock
.ruff_cache/
.mypy_cache/
.dmypy.json
dmypy.json
.pyre/
.pytype/
site/
"""
SETUP_PY: Final[str] = '''\
"""Legacy shim for tools that still expect a setup.py.
All project metadata lives in pyproject.toml and setup.cfg.
"""
from setuptools import setup
setup()
'''
PYPROJECT_PKG_TMPL: Final[str] = """\
[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"
[project]
name = "{pkgname}"
version = "{version}"
readme = "README.md"
authors = [
  {{name = "isaac onagh", email = "mkalafsaz@gmail.com"}}
]
requires-python = ">= 3.12"
[project.scripts]
{pkgname} = "{pkgname}.cli:main"
"""
SETUP_CFG_PKG_TMPL: Final[str] = """\
[options]
package_dir =
    = src
packages = find:
python_requires = >= 3.12
[options.packages.find]
where = src
[mypy]
python_version = 3.12
strict = True
warn_unused_ignores = True
warn_redundant_casts = True
warn_unreachable = True
files = src
[ruff]
line-length = 120
target-version = py312
[tool:pytest]
testpaths = tests
addopts = -ra -q
"""
INIT_PY_TMPL: Final[str] = '__version__ = "{version}"\n'
MAIN_PY: Final[str] = """\
from .cli import app
if __name__ == "__main__":
    app()
"""
CLI_PY_TMPL: Final[str] = """\
import typer
from rich.console import Console
from {pkgname} import utils
app = typer.Typer()
console = Console()
@app.command()
def main() -> None:
    console.print(
        "Replace this message by putting your code into {pkgname}.cli.main"
    )
    utils.do_something_useful()
if __name__ == "__main__":
    app()
"""
CREDENTIALS_PY: Final[str] = """\
import json
import os
from pathlib import Path
from dotenv import load_dotenv
dotenv_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=dotenv_path)
"""
LOGGING_PY: Final[str] = """\
from sys import stdout
from loguru import logger
log_handler_id: int | None = None
def set_logger_level(level: str | int):
    global log_handler_id
    logger.remove(log_handler_id)
    log_handler_id = logger.add(sink=stdout, level=level)
def main():
    logger.remove()
    log_handler_id = logger.add(sink=stdout)
if __name__ == "__main__":
    main()
"""
UTILS_PY: Final[str] = """\
def do_something_useful() -> None:
    print("Replace this with a utility function")
"""
PYPROJECT_SINGLE_TMPL: Final[str] = """\
[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"
[project]
name = "{pkgname}"
version = "{version}"
readme = "README.md"
authors = [
  {{name = "isaac onagh", email = "mkalafsaz@gmail.com"}}
]
requires-python = ">= 3.12"
[project.scripts]
{pkgname} = "{pkgname}:main"
"""
SETUP_CFG_SINGLE_TMPL: Final[str] = """\
[options]
py_modules = {pkgname}
python_requires = >= 3.12
install_requires =
[mypy]
python_version = 3.12
strict = True
warn_unused_ignores = True
warn_redundant_casts = True
warn_unreachable = True
files = {pkgname}.py
[ruff]
line-length = 120
target-version = py312
[tool:pytest]
testpaths = tests
addopts = -ra -q
"""
SINGLE_FILE_PY_TMPL: Final[str] = '''\
"""{pkgname} -- a single-file Python module."""
from __future__ import annotations
__version__ = "{version}"
def main() -> None:
    """Console-script entry point for the ``{pkgname}`` command."""
    print("Hello from {pkgname}")
if __name__ == "__main__":
    main()
'''


def run(cmd: list[str], cwd: Path) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def github_request(
    method: str,
    url: str,
    token: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data: bytes | None = json.dumps(payload).encode() if payload is not None else None
    req: urllib.request.Request = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            body: str = resp.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        detail: str = e.read().decode(errors="replace")
        raise SystemExit(f"GitHub API error {e.code} on {method} {url}:\n{detail}") from e


def get_github_token() -> str:
    token: str | None = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit(f"GITHUB_TOKEN not found. Add it to {ENV_PATH}, e.g.\n    GITHUB_TOKEN=ghp_xxx")
    return token


def get_github_user(token: str) -> str:
    data: dict[str, Any] = github_request("GET", f"{GITHUB_API}/user", token)
    return str(data["login"])


def create_github_repo(
    token: str,
    name: str,
    *,
    private: bool = True,
    description: str = "",
) -> dict[str, Any]:
    return github_request(
        "POST",
        f"{GITHUB_API}/user/repos",
        token,
        {
            "name": name,
            "private": private,
            "description": description,
            "auto_init": False,
        },
    )


def get_or_create_github_repo(
    token: str,
    user: str,
    name: str,
    *,
    private: bool = True,
) -> dict[str, Any]:
    try:
        return github_request("GET", f"{GITHUB_API}/repos/{user}/{name}", token)
    except SystemExit as exc:
        if "404" not in str(exc):
            raise
    print(f"Repo {user}/{name} not found, creating ...")
    return create_github_repo(token, name, private=private)


def render_package_files(pkgname: str) -> dict[Path, str]:
    src_pkg: Path = Path("src") / pkgname
    return {
        Path(".gitignore"): GITIGNORE,
        Path("README.md"): f"# {pkgname}\n",
        Path("pyproject.toml"): PYPROJECT_PKG_TMPL.format(pkgname=pkgname, version=VERSION),
        Path("setup.py"): SETUP_PY,
        Path("setup.cfg"): SETUP_CFG_PKG_TMPL,
        src_pkg / "__init__.py": INIT_PY_TMPL.format(version=VERSION),
        src_pkg / "__main__.py": MAIN_PY,
        src_pkg / "cli.py": CLI_PY_TMPL.format(pkgname=pkgname),
        src_pkg / "credentials.py": CREDENTIALS_PY,
        src_pkg / "logging.py": LOGGING_PY,
        src_pkg / "utils.py": UTILS_PY,
        src_pkg / "py.typed": "",
    }


def render_single_file_files(pkgname: str) -> dict[Path, str]:
    return {
        Path(".gitignore"): GITIGNORE,
        Path("README.md"): f"# {pkgname}\n",
        Path("pyproject.toml"): PYPROJECT_SINGLE_TMPL.format(pkgname=pkgname, version=VERSION),
        Path("setup.py"): SETUP_PY,
        Path("setup.cfg"): SETUP_CFG_SINGLE_TMPL.format(pkgname=pkgname),
        Path(f"{pkgname}.py"): SINGLE_FILE_PY_TMPL.format(pkgname=pkgname, version=VERSION),
    }


def init_project(pkgname: str, *, single_file: bool) -> tuple[Path, list[Path], list[Path]]:
    root: Path = Path.cwd() / pkgname
    root.mkdir(parents=True, exist_ok=True)
    files: dict[Path, str] = render_single_file_files(pkgname) if single_file else render_package_files(pkgname)
    created: list[Path] = []
    skipped: list[Path] = []
    for rel_path, content in files.items():
        abs_path: Path = root / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        if abs_path.exists():
            skipped.append(abs_path)
            continue
        abs_path.write_text(content, encoding="utf-8")
        created.append(abs_path)
    return root, created, skipped


def git_init_and_push(root: Path, remote_url: str) -> None:
    run(["git", "init", "-b", DEFAULT_BRANCH], cwd=root)
    run(["git", "add", "."], cwd=root)
    run(
        ["git", "commit", "--allow-empty", "-m", "Initial commit"],
        cwd=root,
    )
    existing = subprocess.run(
        ["git", "remote"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    if "origin" in existing:
        run(["git", "remote", "set-url", "origin", remote_url], cwd=root)
    else:
        run(["git", "remote", "add", "origin", remote_url], cwd=root)
    run(["git", "push", "-u", "origin", DEFAULT_BRANCH], cwd=root)


def scrub_remote_token(root: Path, user: str, pkgname: str) -> None:
    clean_url: str = f"https://github.com/{user}/{pkgname}.git"
    run(["git", "remote", "set-url", "origin", clean_url], cwd=root)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog=Path(sys.argv[0]).name,
        description=(
            "Scaffold a new Python project, create a GitHub repo, "
            "and push the initial commit. Existing files are never "
            "overwritten."
        ),
    )
    parser.add_argument(
        "pkgname",
        help="Python package / module name (also used as the directory name)",
    )
    parser.add_argument(
        "-s",
        "--single-file",
        action="store_true",
        dest="single_file",
        help=("Create a single-file module (<pkgname>.py) instead of the default src-layout package"),
    )
    return parser.parse_args(argv)


def main() -> None:
    args: argparse.Namespace = parse_args(sys.argv[1:])
    pkgname: str = args.pkgname
    single_file: bool = args.single_file
    if not pkgname.isidentifier():
        raise SystemExit(f"Error: {pkgname!r} is not a valid Python identifier")
    layout: str = "single-file module" if single_file else "src-layout package"
    print(f"Scaffolding {layout} for {pkgname!r}")
    token: str = get_github_token()
    user: str = get_github_user(token)
    print(f"Authenticated as GitHub user: {user}")
    root, created, skipped = init_project(pkgname, single_file=single_file)
    print(f"Project root: {root}")
    print(f"  created: {len(created)} file(s)")
    for path in created:
        print(f"    + {path.relative_to(root)}")
    if skipped:
        print(f"  skipped (already exist): {len(skipped)} file(s)")
        for path in skipped:
            print(f"    = {path.relative_to(root)}")
    get_or_create_github_repo(token, user, pkgname, private=True)
    push_url: str = f"https://{token}@github.com/{user}/{pkgname}.git"
    git_init_and_push(root, push_url)
    scrub_remote_token(root, user, pkgname)
    print(f"\nDone: https://github.com/{user}/{pkgname}")


if __name__ == "__main__":
    main()
