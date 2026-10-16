from __future__ import annotations

import argparse
import io
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests


def read_repos(file_path: Path) -> list[str]:
    if not file_path.exists():
        print(f"Error: {file_path} does not exist")
        sys.exit(1)
    with open(file_path) as f:
        repos = [line.strip() for line in f if line.strip()]
    if not repos:
        print(f"Error: No repositories found in {file_path}")
        sys.exit(1)
    return repos


def validate_repo_format(repo: str) -> bool:
    parts = repo.split("/")
    return len(parts) == 2 and all(parts)


def download_repo_zip(repo: str, base_dir: Path) -> tuple[str, bool, str]:
    if not validate_repo_format(repo):
        return repo, False, f"Invalid format: {repo}"
    user, repo_name = repo.split("/")
    target_dir = base_dir / user / repo_name
    if target_dir.exists():
        return repo, True, f"Already exists: {target_dir}"
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    zip_url = f"https://api.github.com/repos/{repo}/zipball"
    try:
        response = requests.get(zip_url, timeout=30, stream=True)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            root_dir = z.namelist()[0].split("/")[0]
            temp_dir = target_dir.parent / f"_temp_{repo_name}"
            z.extractall(temp_dir)
            extracted_root = temp_dir / root_dir
            if extracted_root.exists():
                import shutil

                for item in extracted_root.iterdir():
                    shutil.move(str(item), str(target_dir / item.name))
                shutil.rmtree(temp_dir)
            else:
                import shutil

                shutil.move(str(temp_dir), str(target_dir))
        return repo, True, f"Successfully downloaded to {target_dir}"
    except requests.RequestException as e:
        return repo, False, f"Download failed: {e!s}"
    except zipfile.BadZipFile:
        return repo, False, "Invalid ZIP file received"
    except Exception as e:
        if target_dir.exists():
            import shutil

            shutil.rmtree(target_dir, ignore_errors=True)
        return repo, False, f"Error: {e!s}"


def main():
    parser = argparse.ArgumentParser(description="Download GitHub repositories as ZIP archives")
    parser.add_argument(
        "file",
        nargs="?",
        default="repos.txt",
        help="Path to file containing repositories (default: repos.txt)",
    )
    parser.add_argument("-o", "--output", default="repos", help="Output directory (default: repos)")
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
        return
    successful = 0
    failed = 0
    skipped = 0
    print(f"\nDownloading with {args.workers} parallel workers to {output_dir.absolute()}")
    print("-" * 40)
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_repo = {executor.submit(download_repo_zip, repo, output_dir): repo for repo in repos}
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
    print(f"  ✅ Successfully downloaded: {successful}")
    print(f"  ⏭️  Already existed: {skipped}")
    print(f"  ❌ Failed: {failed}")
    print(f"  📊 Total: {len(repos)}")


if __name__ == "__main__":
    raise SystemExit(main())
