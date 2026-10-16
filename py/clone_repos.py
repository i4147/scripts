from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from git import GitCommandError, Repo
from git.exc import InvalidGitRepositoryError


def read_repos(path: Path) -> list[str]:
    if not path.exists():
        print(f"Error: {path} does not exist")
        sys.exit(1)
    with open(path) as f:
        repos = [line.strip() for line in f if line.strip()]
    if not repos:
        print(f"Error: No repositories found in {path}")
        sys.exit(1)
    return repos


def validate_repo_format(repo: str) -> bool:
    parts = repo.split("/")
    return len(parts) == 2 and all(parts)


def clone_repo(repo: str, base_dir: Path) -> tuple[str, bool, str]:
    if not validate_repo_format(repo):
        return repo, False, f"Invalid format: {repo} (expected user/repo)"
    user, repo_name = repo.split("/")
    target_dir = base_dir / user / repo_name
    if target_dir.exists():
        try:
            Repo(target_dir)
            return repo, True, f"Already exists: {target_dir}"
        except InvalidGitRepositoryError:
            return repo, False, f"Directory exists but is not a git repo: {target_dir}"
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    clone_url = f"https://github.com/{repo}.git"
    try:
        Repo.clone_from(clone_url, target_dir, depth=1, single_branch=True)
        return repo, True, f"Successfully cloned to {target_dir}"
    except GitCommandError as e:
        error_msg = str(e).strip()
        if target_dir.exists():
            import shutil

            shutil.rmtree(target_dir, ignore_errors=True)
        return repo, False, f"Clone failed: {error_msg}"
    except Exception as e:
        if target_dir.exists():
            import shutil

            shutil.rmtree(target_dir, ignore_errors=True)
        return repo, False, f"Error: {e!s}"


def main():
    parser = argparse.ArgumentParser(description="Clone GitHub repositories in parallel from a text file")
    parser.add_argument(
        "file",
        nargs="?",
        default="repos.txt",
        help="Path to file containing repositories (default: repos.txt)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="repos",
        help="Output directory for cloned repositories (default: repos)",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be cloned without actually cloning",
    )
    args = parser.parse_args()
    repos_file = Path(args.file)
    output_dir = Path(args.output)
    repos = read_repos(repos_file)
    print(f"Found {len(repos)} repositories to clone")
    if args.dry_run:
        print("\nDry run - would clone:")
        for repo in repos:
            if validate_repo_format(repo):
                user, repo_name = repo.split("/")
                target = output_dir / user / repo_name
                status = "EXISTS" if target.exists() else "NEW"
                print(f"  [{status}] {repo} -> {target}")
            else:
                print(f"  [INVALID] {repo}")
        return
    successful = 0
    failed = 0
    skipped = 0
    print(f"\nCloning with {args.workers} parallel workers to {output_dir.absolute()}")
    print("-" * 40)
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_repo = {executor.submit(clone_repo, repo, output_dir): repo for repo in repos}
        for future in as_completed(future_to_repo):
            repo = future_to_repo[future]
            try:
                repo_name, success, message = future.result()
                if success:
                    if "Already exists" in message:
                        skipped += 1
                        print(f"⏭️  {repo}: {message}")
                    else:
                        successful += 1
                        print(f"✅ {repo}: {message}")
                else:
                    failed += 1
                    print(f"❌ {repo}: {message}")
            except Exception as e:
                failed += 1
                print(f"❌ {repo}: Unexpected error: {e!s}")
    print("-" * 40)
    print("\nSummary:")
    print(f"  ✅ Successfully cloned: {successful}")
    print(f"  ⏭️  Already existed: {skipped}")
    print(f"  ❌ Failed: {failed}")
    print(f"  📊 Total: {len(repos)}")


if __name__ == "__main__":
    raise SystemExit(main())
