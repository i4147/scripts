import subprocess
import sys
from pathlib import Path

import regex as re
import requests
from tqdm import tqdm


def get_repo_size(repo_url: str):
    if not repo_url.startswith(("http://", "https://", "git@")):
        repo_url = f"https://github.com/{repo_url}"
    if repo_url.startswith("git@"):
        repo_url = repo_url.replace(
            "git@github.com:",
            "https://github.com/",
        )
    api_url = repo_url.replace("github.com", "api.github.com/repos", 1)
    try:
        response = requests.get(api_url)
        response.raise_for_status()
        size_kb = response.json().get("size", 0)
        return size_kb / 1024
    except Exception as e:
        print(f"[ERROR] Could not fetch repo size: {e}")
        return 0


def clone_repo(repo: str, branch: str = "main") -> None:
    print(f"[INFO] Cloning repository: {repo} (branch: {branch})")
    cmd = [
        "git",
        "clone",
        "--depth",
        "1",
        "--single-branch",
        "--branch",
        branch,
        repo,
        "--progress",
    ]
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        for line in process.stderr:
            line = line.strip()
            if "Receiving objects:" in line:
                progress = re.search(
                    r"(\d+)%.*?(\d+\.?\d*)\s*MB",
                    line,
                )
                if progress:
                    percent, mb = progress.groups()
                    tqdm.write(f"[PROGRESS] {percent}% ({mb} MB)")
                else:
                    tqdm.write(f"[PROGRESS] {line}")
            elif "fatal:" in line:
                raise Exception(line)
            elif line:
                tqdm.write(f"[INFO] {line}")
    except Exception as e:
        msg = f"[ERROR] Clone failed: {e}"
        raise Exception(msg)


def main() -> None:
    if len(sys.argv) < 2:
        print("[ERROR] Usage: script.py <repository_url>")
        print("Example: script.py git@github.com:user/repo.git")
        print("Example: script.py https://github.com/user/repo")
        return
    repo = sys.argv[1].strip()
    print(f"[INFO] Checking repository size for: {repo}")
    size_mb = get_repo_size(repo)
    if size_mb > 10:
        print(f"[WARNING] Repository size is {size_mb:.2f} MB. Continue? (y/n)")
        if input().lower() != "y":
            print("[INFO] Aborted by user.")
            return
    try:
        clone_repo(repo, "main")
    except Exception as e:
        if "not found" in str(e):
            print("[WARNING] 'main' branch not found, trying 'master'...")
            clone_repo(repo, "master")
        else:
            print(f"[ERROR] {e}")
            return
    if Path(".gitmodules").exists():
        print("[INFO] Submodules found. Initialize and update? (y/n)")
        if input().lower() == "y":
            print("[INFO] Initializing and updating submodules...")
            subprocess.run(
                [
                    "git",
                    "submodule",
                    "update",
                    "--init",
                    "--recursive",
                ],
                check=True,
                capture_output=True,
            )
            print("[INFO] Submodules updated.")


if __name__ == "__main__":
    main()
