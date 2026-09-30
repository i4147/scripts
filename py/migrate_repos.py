#!/usr/bin/env python3
"""Migrate standard working-tree Git repositories in the current directory.

Requires Git and GitHub CLI (gh) to be installed and authenticated.
"""

import os
import subprocess
import sys
from pathlib import Path

SKIP_DIRS = {"cpython", "neovim-source"}
NEW_OWNER = "i4147"
COMMIT_MESSAGE = "Auto-commit uncommitted changes before migration"


def run_command(command, cwd):
    """Run a command and raise a useful error if it fails."""
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"Required command not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"Command failed ({' '.join(command)}): {details or exc.returncode}") from exc


def migrate_repository(repo_path):
    repo_name = repo_path.name
    new_repo_path = f"{NEW_OWNER}/{repo_name}"
    print(f"\nMigrating: {repo_name}")

    # Ensure this is a non-bare repository with a working tree.
    result = run_command(["git", "rev-parse", "--is-bare-repository"], cwd=repo_path)
    if result.stdout.strip() != "false":
        print(f"Skipping {repo_name}: repository is bare.")
        return
    run_command(["git", "rev-parse", "--show-toplevel"], cwd=repo_path)

    status = run_command(["git", "status", "--porcelain"], cwd=repo_path)
    if status.stdout.strip():
        print(f"Uncommitted changes found in {repo_name}; committing...")
        run_command(["git", "add", "-A"], cwd=repo_path)
        run_command(["git", "commit", "-m", COMMIT_MESSAGE], cwd=repo_path)

    print(f"Creating remote repository {new_repo_path}...")
    run_command(
        ["gh", "repo", "create", new_repo_path, "--public", "--confirm"],
        cwd=repo_path,
    )

    remote_url = f"git@github.com:{new_repo_path}.git"
    print(f"Setting origin to {remote_url}...")
    remotes = run_command(["git", "remote"], cwd=repo_path).stdout.splitlines()
    if "origin" in remotes:
        run_command(["git", "remote", "set-url", "origin", remote_url], cwd=repo_path)
    else:
        run_command(["git", "remote", "add", "origin", remote_url], cwd=repo_path)

    print("Pushing all branches and tags...")
    run_command(["git", "push", "-u", "origin", "--all"], cwd=repo_path)
    run_command(["git", "push", "origin", "--tags"], cwd=repo_path)
    print(f"Successfully migrated {repo_name}.")


def migrate():
    root = Path.cwd()
    failures = []
    for entry in os.scandir(root):
        if not entry.is_dir(follow_symlinks=False):
            continue
        if entry.name in SKIP_DIRS:
            print(f"Skipping excluded directory: {entry.name}")
            continue

        repo_path = Path(entry.path)
        # Standard clones use a .git directory; .git files (worktrees/submodules)
        # and bare repositories are intentionally not included.
        if not (repo_path / ".git").is_dir():
            continue

        try:
            migrate_repository(repo_path)
        except RuntimeError as exc:
            failures.append((entry.name, str(exc)))
            print(f"Migration failed for {entry.name}: {exc}", file=sys.stderr)

    if failures:
        print(f"\nFinished with {len(failures)} migration failure(s):", file=sys.stderr)
        for repo_name, error in failures:
            print(f"- {repo_name}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(migrate())
