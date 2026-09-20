import argparse
import io
import shutil
import sys
import zipfile
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Final
import requests
from loguru import logger
NUM_WORKERS = 8
REQUEST_TIMEOUT = 30
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
def download_repo_zip(repo, base_dir):
    if not validate_repo_format(repo):
        return repo, False, f"Invalid format: {repo}"
    user, repo_name = repo.split("/")
    target_dir = base_dir / user / repo_name
    if target_dir.exists():
        return repo, True, f"Already exists: {target_dir}"
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    zip_url = f"https://api.github.com/repos/{repo}/zipball"
    try:
        response = requests.get(zip_url, timeout=REQUEST_TIMEOUT, stream=True)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            root_dir = z.namelist()[0].split("/")[0]
            temp_dir = target_dir.parent / f"_temp_{repo_name}"
            z.extractall(temp_dir)
            extracted_root = temp_dir / root_dir
            if extracted_root.exists():
                target_dir.mkdir(parents=True, exist_ok=True)
                for item in extracted_root.iterdir():
                    shutil.move(str(item), str(target_dir / item.name))
                shutil.rmtree(temp_dir)
            else:
                shutil.move(str(temp_dir), str(target_dir))
        return repo, True, f"Successfully downloaded to {target_dir}"
    except requests.RequestException as e:
        return repo, False, f"Download failed: {e!s}"
    except zipfile.BadZipFile:
        return repo, False, "Invalid ZIP file received"
    except Exception as e:
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        return repo, False, f"Error: {e!s}"
def main():
    parser = argparse.ArgumentParser(
        description="Download GitHub repositories as ZIP archives"
    )
    parser.add_argument(
        "file",
        nargs="?",
        default="repos.txt",
        help="Path to file containing repositories (default: repos.txt)",
    )
    parser.add_argument(
        "-o", "--output", default="repos", help="Output directory (default: repos)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be downloaded without downloading",
    )
    args = parser.parse_args()
    repos_file = Path(args.file)
    output_dir = Path(args.output)
    repos = read_repos(repos_file)
    print(f"Found {len(repos)} repositories to download")
    if args.dry_run:
        print("\nDry run - would download:")
        for repo in repos:
            if validate_repo_format(repo):
                user, repo_name = repo.split("/")
                target = output_dir / user / repo_name
                status = "EXISTS" if target.exists() else "NEW"
                print(f"  [{status}] {repo} -> {target}")
            else:
                print(f"  [INVALID] {repo}")
        return 0
    successful = 0
    failed = 0
    skipped = 0
    print(
        f"\nDownloading with {NUM_WORKERS} parallel workers to {output_dir.absolute()}"
    )
    print("-" * 40)
    with Pool(processes=NUM_WORKERS) as pool:
        results = [
            pool.apply_async(download_repo_zip, (repo, output_dir)) for repo in repos
        ]
        pool.close()
        for result in results:
            try:
                repo_name, success, message = result.get()
                if success:
                    if "Already exists" in message:
                        skipped += 1
                        print(f"⏭️  {repo_name}: {message}")
                    else:
                        successful += 1
                        print(f"✅ {repo_name}: {message}")
                else:
                    failed += 1
                    logger.error(f"❌ {repo_name}: {message}")
            except Exception as e:
                failed += 1
                logger.error(f"❌ Unexpected error: {e!s}")
        pool.join()
    print("-" * 40)
    print("\nSummary:")
    print(f"  ✅ Successfully downloaded: {successful}")
    print(f"  ⏭️  Already existed: {skipped}")
    print(f"  ❌ Failed: {failed}")
    print(f"  📊 Total: {len(repos)}")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
