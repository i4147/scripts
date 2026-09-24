import sys
from pathlib import Path
from datetime import datetime

from git import Repo, InvalidGitRepositoryError


def main() -> None:
    cwd = Path.cwd()
    try:
        repo = Repo(cwd, search_parent_directories=True)
        print(f"Found existing git repository at {repo.git_dir}")
    except InvalidGitRepositoryError:
        repo = Repo.init(cwd)
        print("Repository initialized.")

    if not repo.is_dirty(untracked_files=True):
        print("No changes to commit.")
        return

    repo.git.add("--all")

    commit_message = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        commit = repo.index.commit(commit_message)
        print(f'Committed with message: "{commit_message}"')
        print(f"Commit hash: {commit.hexsha[:7]}")
    except Exception as e:
        print(f"Commit failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
