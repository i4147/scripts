from __future__ import annotations

import argparse
from pathlib import Path
from typing import Final

from dulwich import porcelain
from dulwich.errors import NotGitRepository
from github import Github
from github.GithubException import GithubException, UnknownObjectException
from github.Repository import Repository
from loguru import logger

LARGE_REPO_THRESHOLD_MB: Final[float] = 5.0
DEFAULT_BRANCH_FALLBACK: Final[str] = "master"
GITHUB_SSH_PREFIX: Final[str] = "git@github.com:"
GITHUB_HTTP_PREFIXES: Final[tuple[str, ...]] = ("http://", "https://")
GITHUB_HOST: Final[str] = "github.com/"
DEFAULT_CLONE_DEPTH: Final[int] = 1
GITMODULES_FILENAME: Final[str] = ".gitmodules"


def get_github_client(token: str | None = None) -> Github:
    if token:
        return Github(token)
    return Github()


def parse_repo_url(txt: str) -> tuple[str, str]:
    txt = txt.strip()
    txt = txt.removesuffix(".git")
    if txt.startswith(GITHUB_SSH_PREFIX):
        txt = txt.replace(GITHUB_SSH_PREFIX, "")
    if txt.startswith(GITHUB_HTTP_PREFIXES):
        txt = txt.split(GITHUB_HOST, 1)[-1]
    parts = txt.split("/")
    if len(parts) >= 2:
        return parts[-2], parts[-1]
    raise ValueError(f"Invalid repository format: {txt}")


def get_repo(repo_url: str, github_client: Github) -> Repository:
    try:
        owner, repo_name = parse_repo_url(repo_url)
        print(f"Fetching repository: {owner}/{repo_name}")
        repo = github_client.get_user(owner).get_repo(repo_name)
        _ = repo.size
        print(f"Repository found: {repo.full_name}")
        return repo
    except UnknownObjectException:
        raise ValueError(f"Repository not found: {repo_url}")
    except GithubException as e:
        raise Exception(f"GitHub API error: {e.status} {e.data}")


def get_repo_size(repo: Repository) -> float:
    try:
        size_kb = repo.size
        size_mb = size_kb / 1024
        print(f"Repository size: {size_mb:.2f} MB")
        return size_mb
    except Exception as e:
        logger.error(f"Could not fetch repo size: {e}")
        return 0.0


def get_default_branch(repo: Repository) -> str:
    try:
        default_branch = repo.default_branch
        print(f"Default branch: {default_branch}")
        return default_branch
    except Exception as e:
        logger.warning(f"Could not determine default branch: {e}")
        return "main"


def build_clone_url(repo: Repository) -> str:
    return repo.clone_url


def resolve_clone_target(clone_url: str) -> Path:
    name = Path(clone_url.rstrip("/").removesuffix(".git")).name
    return Path.cwd() / name


def clone_repo(clone_url: str, branch: str, depth: int = 1) -> Path:
    depth_msg = f"depth={depth}" if depth is not None else "full history"
    print(f"Cloning repository from {clone_url} (branch: {branch}, {depth_msg})")
    target_path = resolve_clone_target(clone_url)
    try:
        porcelain.clone(
            source=clone_url,
            target=str(target_path),
            branch=branch.encode("utf-8"),
            depth=depth,
        )
        print(f"Clone completed successfully at {target_path}.")
        return target_path
    except Exception as e:
        raise Exception(f"[ERROR] Clone failed: {e}")


def has_submodules(repo_path: Path) -> bool:
    if (repo_path / GITMODULES_FILENAME).is_file():
        return True
    try:
        for candidate in repo_path.rglob(GITMODULES_FILENAME):
            if candidate.is_file():
                return True
    except OSError as e:
        logger.warning(f"Error scanning for submodules: {e}")
    return False


def _update_submodules_recursive(repo_root: Path) -> None:
    processed: set[Path] = set()
    pending: list[Path] = [repo_root]

    while pending:
        current_root = pending.pop()
        if current_root in processed:
            continue
        processed.add(current_root)

        if not has_submodules(current_root):
            continue

        print(f"Updating submodules in {current_root}...")
        try:
            porcelain.submodule_update(
                root=str(current_root),
                recursive=True,
            )
            print(f"Submodules updated in {current_root}.")
        except NotGitRepository as e:
            raise Exception(f"Submodule update failed in {current_root}: {e}")
        except Exception as e:
            raise Exception(f"Submodule update failed in {current_root}: {e}")

        for sub in current_root.iterdir():
            if not sub.is_dir():
                continue
            if sub in processed:
                continue
            if has_submodules(sub):
                pending.append(sub)


def init_submodules(repo_path: Path) -> None:
    if not has_submodules(repo_path):
        print("No submodules found.")
        return

    print("Submodules found. Initialize and update? (y/n)")
    if input().lower() != "y":
        print("Submodule initialization skipped.")
        return

    try:
        _update_submodules_recursive(repo_path)
    except Exception as e:
        raise Exception(f"Submodule update failed: {e}")


def confirm_large_repo(size_mb: float) -> bool:
    if size_mb > LARGE_REPO_THRESHOLD_MB:
        logger.warning(f"Repository size is {size_mb:.2f} MB. Continue? (y/n)")
        return input().lower() == "y"
    return True


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="script.py",
        description="Clone a GitHub repository using dulwich.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  script.py owner/repo\n"
            "  script.py https://github.com/owner/repo\n"
            "  script.py git@github.com:owner/repo.git -d\n"
        ),
    )
    parser.add_argument(
        "repository_url",
        help="Repository identifier or URL (owner/repo, HTTPS, or SSH).",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="GitHub personal access token (increases rate limit).",
    )
    parser.add_argument(
        "-d",
        "--depth",
        default=1,
        action="store_true",
        help=("Perform a shallow clone with depth 1. Without this flag the full history is cloned."),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    repo_url: str = args.repository_url.strip()
    token: str | None = args.token
    depth: int | None = DEFAULT_CLONE_DEPTH if args.depth else None

    try:
        github_client = get_github_client(token)
        if token:
            print(f"Authenticated as: {github_client.get_user().login}")
    except GithubException as e:
        logger.error(f"Authentication failed: {e}")
        return 1

    try:
        repo = get_repo(repo_url, github_client)
    except (ValueError, Exception) as e:
        logger.error(f"{e}")
        return 1

    size_mb = get_repo_size(repo)
    if not confirm_large_repo(size_mb):
        print("Aborted by user.")
        return 0

    default_branch = get_default_branch(repo)
    clone_url = build_clone_url(repo)

    try:
        repo_path = clone_repo(clone_url, default_branch, depth)
    except Exception as e:
        if "not found" in str(e).lower() or "fatal:" in str(e):
            alt_branch = DEFAULT_BRANCH_FALLBACK if default_branch == "main" else "main"
            logger.warning(f"Branch '{default_branch}' failed, trying '{alt_branch}'...")
            try:
                repo_path = clone_repo(clone_url, alt_branch, depth)
            except Exception as e2:
                logger.error(f"Clone with both branches failed: {e2}")
                return 1
        else:
            logger.error(f"{e}")
            return 1

    try:
        init_submodules(repo_path)
    except Exception as e:
        logger.warning(f"Submodule handling failed: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
