#!/data/data/com.termux/files/usr/bin/python
"""Write a Python script that recursively scans the current working directory and all of its subdirectories to discover every Git repository (any folder containing a Git metadata directory), then updates each discovered repository by pulling the latest changes from its remote. The script should not descend into a folder once it has been identified as a repository, and it should report progress clearly as it works.
For each repository found, the script should determine its currently checked-out branch and display it. If a repository has no configured remote, it should be recorded as a failure rather than crashing the run. Otherwise, it should attempt to pull updates and record whether the operation succeeded or failed, capturing any Git-related errors gracefully without stopping the processing of the remaining repositories.
Use human-readable console output with a clear per-repository status line, an emoji-style or otherwise visually distinct header for each repository, and a final summary listing the total number of repositories found, how many were pulled successfully, and which ones failed along with the reason. If no repositories are found, the script should inform the user and exit cleanly.
The script should be robust to permission issues or unreadable directories by skipping them without aborting. Display all repository paths relative to the starting directory for readability. The tool is intended to be run from a terminal with no required command-line arguments, and it should rely on a Git-interacting library available for Python to perform repository operations.
---"""

from __future__ import annotations
from pathlib import Path
from git import GitCommandError, Repo


def find_git_repos(root_path: Path) -> list[Path]:
    git_repos = []
    for item in root_path.iterdir():
        if not item.is_dir():
            continue
        if (item / ".git").exists():
            git_repos.append(item)
        else:
            git_repos.extend(find_git_repos(item))
    return git_repos


def git_pull_all() -> None:
    cwd = Path.cwd()
    print(f"🔍 Scanning for git repositories in: {cwd}")
    repos = find_git_repos(cwd)
    if not repos:
        print("No git repositories found")
        return
    print(f"Found {len(repos)} git repository(ies)\n")
    pulled_repos = []
    failed_repos = []
    for repo_path in repos:
        print(f"📁 Repository: {repo_path.relative_to(cwd)}")
        try:
            repo = Repo(repo_path)
            current_branch = repo.active_branch.name
            print(f"   Branch: {current_branch}")
            if not repo.remotes:
                failed_repos.append((repo_path, "No remote configured"))
                print("   ❌ No remote configured")
                continue
            remote_name = repo.remotes[0].name
            pull_result = repo.remotes[remote_name].pull()
            success = False
            for info in pull_result:
                if hasattr(info, "flags"):
                    if info.flags & info.ERROR:
                        failed_repos.append((repo_path, str(info.note)))
                        print(f"   ❌ Failed: {info.note}")
                    else:
                        success = True
                        if hasattr(info, "commit") and info.commit:
                            print(f"   ✅ Pulled successfully: {info.commit}")
                        else:
                            print("   ℹ️  Already up to date")
                else:
                    success = True
                    print("   ✅ Pull completed")
            if success:
                pulled_repos.append(repo_path)
        except GitCommandError as e:
            failed_repos.append((repo_path, str(e)))
            print(f"   ❌ Git error: {e}")
        except Exception as e:
            failed_repos.append((repo_path, f"Unexpected error: {e!s}"))
            print(f"   ❌ Error: {e}")
    print("\n" + "=" * 40)
    print("SUMMARY")
    print("-" * 40)
    if pulled_repos:
        print(f"\n✅ Successfully pulled ({len(pulled_repos)} repos):")
        for repo_path in pulled_repos:
            print(f"   - {repo_path.relative_to(cwd)}")
    if failed_repos:
        print(f"\n❌ Failed ({len(failed_repos)} repos):")
        for repo_path, error in failed_repos:
            print(f"   - {repo_path.relative_to(cwd)}: {error}")


if __name__ == "__main__":
    try:
        git_pull_all()
    except KeyboardInterrupt:
        print("\n\n⚠️  Operation cancelled by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
