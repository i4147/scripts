#!/data/data/com.termux/files/usr/bin/python
"""Write a Python script that scans a given directory tree for Git repositories and reports the working-tree status of each one, running the checks concurrently to keep the scan fast.

The script should accept a root directory (defaulting to the current directory) and locate every immediate subdirectory or nested folder that is a Git repository. For each repository, it should determine whether there are uncommitted or untracked changes. Repositories with no changes should be reported as clean, while repositories with changes should be reported with a concise summary of the modified, added, deleted, or untracked files, showing a limited number of example entries followed by an indication of how many more exist. Folders that are not Git repositories should be flagged as such, and any Git command that fails or times out should produce a clear error message for that repository without stopping the overall scan.

Key behaviors:
- Process multiple repositories in parallel using a sensible number of worker processes based on the machine's available CPU cores.
- Enforce a short timeout on each Git status check so that a hanging repository cannot block the whole run.
- Produce a readable, organized report to standard output that lists each repository path along with its status, grouping or ordering results so that repositories needing attention are easy to spot.
- Exit with a non-zero status code if any repository has uncommitted changes or encountered errors, and zero otherwise, so the script can be used in automation.
- Handle invalid or missing root paths gracefully with a helpful message.

Inputs: an optional root directory path supplied on the command line.
Outputs: a human-readable status report printed to the console and an appropriate process exit code.
---"""

from __future__ import annotations

import subprocess
import sys
from multiprocessing import Pool, cpu_count
from pathlib import Path


def get_repo_status(repo_path: Path) -> tuple[Path, bool, str | None]:
    try:
        git_dir = repo_path / ".git"
        if not git_dir.exists() or not git_dir.is_dir():
            return (repo_path, False, "Not a git repository")
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return (repo_path, False, f"Git error: {result.stderr.strip()}")
        has_changes = bool(result.stdout.strip())
        if has_changes:
            lines = result.stdout.strip().split("\n")
            changes = []
            for line in lines:
                status = line[:2]
                file = line[3:]
                if status.strip():
                    changes.append(f"{status} {file}")
            change_summary = ", ".join(changes[:5])
            if len(changes) > 5:
                change_summary += f" (+{len(changes) - 5} more)"
            return (repo_path, True, change_summary)
        else:
            return (repo_path, False, "Clean")
    except subprocess.TimeoutExpired:
        return (repo_path, False, "Timeout checking git status")
    except Exception as e:
        return (repo_path, False, f"Error: {e!s}")


def find_git_repos(directory: Path) -> list[Path]:
    repos = []
    for item in directory.iterdir():
        if item.is_dir() and not item.name.startswith(".") and (item / ".git").is_dir():
            repos.append(item)
    return repos


def print_result(result: tuple[Path, bool, str | None]) -> None:
    path, has_changes, info = result
    if not has_changes:
        print(f"✓ {path.name}: No changes")
        if info and info != "Clean":
            print(f"  └─ {info}")
    else:
        print(f"✗ {path.name}: CHANGES DETECTED")
        if info:
            print(f"  └─ {info}")


def main():
    root_dir = Path.cwd()
    print(f"Scanning for git repositories in: {root_dir}\n")
    repos = find_git_repos(root_dir)
    if not repos:
        print("No git repositories found in current directory.")
        return
    print(f"Found {len(repos)} git repository(ies)\n")
    num_processes = min(cpu_count(), len(repos), 8)
    print(f"Checking repositories using {num_processes} process(es)...\n")
    with Pool(processes=num_processes) as pool:
        results = pool.map(get_repo_status, repos)
    changed_count = sum(1 for _, has_changes, _ in results if has_changes)
    if changed_count > 0:
        print("=" * 40)
        print(f"⚠️  Found {changed_count} repository(ies) with changes")
        print("=" * 40)
    else:
        print("=" * 40)
        print("✅ All repositories are clean")
        print("=" * 40)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n\nScan interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)
