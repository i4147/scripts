from __future__ import annotations
import sys
from datetime import datetime
from pathlib import Path
from dulwich import porcelain
from dulwich.errors import GitProtocolError, NotGitRepository
from dulwich.repo import Repo


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


def main() -> None:
    repo = open_repo()
    copy_global_gitignore()
    try:
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
