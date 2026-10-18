#!/data/data/com.termux/files/usr/bin/python
"""Write a Python script that recursively scans the current working directory and all of its subdirectories, identifies every folder that is a Git repository (contains a `.git` directory), and for each one discards any local uncommitted changes to tracked files so the working tree matches the last committed state. For each repository processed, the script should print a clear progress message showing the repository's path. If the operation fails for a particular repository, the script should print a warning identifying that repository and continue processing the remaining ones without stopping. Once all repositories have been handled, the script should print a completion message and exit cleanly. The script should be self-contained, run from the command line with no required arguments, and rely only on the standard library.
---"""

from __future__ import annotations
import os
import subprocess
from pathlib import Path


def is_git_repo(path: Path) -> bool:
    return (path / ".git").is_dir()


def git_pull(repo_path: Path) -> None:
    print(f"\n==> Pulling in repo: {repo_path}")
    try:
        subprocess.run(["git", "-C", str(repo_path), "restore", "."], check=True)
    except subprocess.CalledProcessError:
        print(f"⚠️  git pull failed in: {repo_path}")


def main() -> None:
    root = Path.cwd()
    for dirpath, _dirnames, _filenames in os.walk(root):
        current = Path(dirpath)
        if is_git_repo(current):
            git_pull(current)
    print("\nDone.")


if __name__ == "__main__":
    raise SystemExit(main())
