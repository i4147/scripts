import argparse
import shutil
import sys
from multiprocessing import Pool
from pathlib import Path
from typing import Final
import requests
from dulwich import porcelain
from dulwich.errors import NotGitRepository
from dulwich.repo import Repo
from loguru import logger

MAX_SIZE_MB = 5
MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024
DEFAULT_WORKERS = 8


def read_repos(path):
    if not path.exists():
        logger.error(f"Error: {path} does not exist")
        sys.exit(1)
    with open(path) as f:
        repos = [line.strip() for line in f if line.strip()]
    if not repos:
        logger.error(f"Error: No repositories found in {path}")
        sys.exit(1)
    return repos


def validate_repo_format(repo):
    parts = repo.split("/")
    return len(parts) == 2 and all(parts)


def check_repo_size(repo):
    api_url = f"https://api.github.com/repos/{repo}"
    try:
        response = requests.get(api_url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            size_kb_raw = data.get("size", 0)
            size_kb = int(size_kb_raw) if isinstance(size_kb_raw, (int, float, str)) else 0
            size_bytes = size_kb * 1024
            return size_bytes <= MAX_SIZE_BYTES, size_bytes
        return True, 0
    except Exception:
        return True, 0


def clone_repo(repo, base_dir):
    if not validate_repo_format(repo):
        return repo, False, f"Invalid format: {repo} (expected user/repo)"
    user, repo_name = repo.split("/")
    target_dir = base_dir / user / repo_name
    if target_dir.exists():
        try:
            Repo(str(target_dir))
            return repo, True, f"Already exists: {target_dir}"
        except NotGitRepository:
            return repo, False, f"Directory exists but is not a git repo: {target_dir}"
    is_small, size_bytes = check_repo_size(repo)
    if not is_small:
        return repo, False, f"Too large ({fsz(size_bytes)} > {MAX_SIZE_MB}MB)"
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    clone_url = f"https://github.com/{repo}.git"
    try:
        porcelain.clone(clone_url, str(target_dir), depth=1, bare=False)
        return repo, True, f"Successfully cloned to {target_dir} ({fsz(size_bytes)})"
    except Exception as e:
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        return repo, False, f"Clone failed: {e!s}"


def remove_from_repos_file(path, repos_to_remove):
    if not repos_to_remove:
        return
    current_repos = read_repos(path)
    updated_repos = [repo for repo in current_repos if repo not in repos_to_remove]
    with open(path, "w") as f:
        f.write("\n".join(updated_repos) + "\n" if updated_repos else "")
    print(f"\nRemoved {len(repos_to_remove)} repos from {path}")


def parse_args():
    parser = argparse.ArgumentParser(description="Clone GitHub repositories using pure Python (dulwich)")
    parser.add_argument(
        "file",
        nargs="?",
        default="repos.txt",
        help="Path to file containing repositories (default: repos.txt)",
    )
    parser.add_argument("-o", "--output", default="repos", help="Output directory (default: repos)")
    parser.add_argument(
        "--max-size",
        type=int,
        default=MAX_SIZE_MB,
        help=f"Maximum repo size in MB (default: {MAX_SIZE_MB})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be cloned without actually cloning",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Don't remove cloned repos from repos.txt",
    )
    return parser.parse_args()


def main():
    global MAX_SIZE_BYTES
    args = parse_args()
    if args.max_size != MAX_SIZE_MB:
        MAX_SIZE_BYTES = args.max_size * 1024 * 1024
    repos_file = Path(args.file)
    output_dir = Path(args.output)
    repos = read_repos(repos_file)
    print(f"Found {len(repos)} repositories to clone")
    print(f"Max repo size: {args.max_size}MB")
    if args.dry_run:
        print("\nDry run - checking sizes:")
        for repo in repos:
            if validate_repo_format(repo):
                user, repo_name = repo.split("/")
                target = output_dir / user / repo_name
                is_small, size = check_repo_size(repo)
                if target.exists():
                    print(f"  [EXISTS] {repo} -> {target}")
                elif not is_small:
                    print(f"  [TOO LARGE] {repo} ({fsz(size)})")
                else:
                    print(f"  [OK] {repo} -> {target} ({fsz(size)})")
            else:
                print(f"  [INVALID] {repo}")
        return 0
    successful = 0
    failed = 0
    skipped = 0
    successfully_cloned = set()
    print(f"\nCloning with {DEFAULT_WORKERS} parallel workers to {output_dir.absolute()}")
    print("-" * 40)
    with Pool(processes=DEFAULT_WORKERS) as pool:
        async_results = [(repo, pool.apply_async(clone_repo, (repo, output_dir))) for repo in repos]
        for repo, async_result in async_results:
            try:
                repo_name, success, message = async_result.get()
                if success:
                    if "Already exists" in message:
                        skipped += 1
                        print(f"⏭️  {repo}: {message}")
                        successfully_cloned.add(repo)
                    else:
                        successful += 1
                        print(f"✅ {repo}: {message}")
                        successfully_cloned.add(repo)
                else:
                    failed += 1
                    logger.error(f"❌ {repo}: {message}")
            except Exception as e:
                failed += 1
                logger.error(f"❌ {repo}: Unexpected error: {e!s}")
    if not args.no_cleanup and successfully_cloned:
        remove_from_repos_file(repos_file, successfully_cloned)
    print("-" * 40)
    print("\nSummary:")
    print(f"  ✅ Successfully cloned: {successful}")
    print(f"  ⏭️  Already existed: {skipped}")
    print(f"  ❌ Failed: {failed}")
    print(f"  📊 Total processed: {len(repos)}")
    if not args.no_cleanup and successfully_cloned:
        remaining = len(read_repos(repos_file))
        print(f"  📝 Remaining in {repos_file}: {remaining}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
