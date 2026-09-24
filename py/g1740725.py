import re
import subprocess
import sys
from pathlib import Path

from github import Github
from github.GithubException import GithubException, UnknownObjectException
from github.Repository import Repository
from tqdm import tqdm

SKIP_DIRS = frozenset({"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"})


def get_github_client(token: str | None = None) -> Github:
    if token:
        return Github(token)
    return Github()


def parse_repo_url(txt: str) -> tuple[str, str]:
    txt = txt.strip()
    if txt.endswith(".git"):
        txt = txt[:-4]
    if txt.startswith("git@github.com:"):
        txt = txt.replace("git@github.com:", "")
    if txt.startswith("http://") or txt.startswith("https://"):
        txt = txt.split("github.com/", 1)[-1]
    parts = txt.split("/")
    if len(parts) >= 2:
        return parts[-2], parts[-1]
    raise ValueError(f"Invalid repository format: {txt}")


def get_repo(repo_url: str, github_client: Github) -> Repository:
    try:
        owner, repo_name = parse_repo_url(repo_url)
        print(f"[INFO] Fetching repository: {owner}/{repo_name}")
        repo = github_client.get_user(owner).get_repo(repo_name)
        _ = repo.size
        print(f"[INFO] Repository found: {repo.full_name}")
        return repo
    except UnknownObjectException:
        raise ValueError(f"Repository not found: {repo_url}")
    except GithubException as e:
        raise Exception(f"GitHub API error: {e.status} {e.data}")


def get_repo_size(repo: Repository) -> float:
    try:
        size_kb = repo.size
        size_mb = size_kb / 1024
        print(f"[INFO] Repository size: {size_mb:.2f} MB")
        return size_mb
    except Exception as e:
        print(f"[ERROR] Could not fetch repo size: {e}")
        return 0


def get_default_branch(repo: Repository) -> str:
    try:
        default_branch = repo.default_branch
        print(f"[INFO] Default branch: {default_branch}")
        return default_branch
    except Exception as e:
        print(f"[WARNING] Could not determine default branch: {e}")
        return "main"


def build_clone_url(repo: Repository) -> str:
    return repo.clone_url


def clone_repo(clone_url: str, branch: str) -> None:
    print(f"[INFO] Cloning repository from {clone_url} (branch: {branch})")
    cmd = [
        "git",
        "clone",
        "--depth",
        "1",
        "--single-branch",
        "--branch",
        branch,
        clone_url,
        "--progress",
    ]
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        for line in process.stderr:
            line = line.strip()
            if "Receiving objects:" in line or "Resolving deltas:" in line:
                progress = re.search(r"(\d+)%.*?(\d+\.?\d*)\s*([KM]iB)", line)
                if progress:
                    percent, size, unit = progress.groups()
                    tqdm.write(f"[PROGRESS] {percent}% ({size} {unit})")
                else:
                    tqdm.write(f"[PROGRESS] {line}")
            elif "fatal:" in line:
                raise Exception(line)
            elif line:
                tqdm.write(f"[INFO] {line}")
        returncode = process.wait()
        if returncode != 0:
            raise Exception(f"git clone failed with code {returncode}")
        print("[INFO] Clone completed successfully.")
    except Exception as e:
        raise Exception(f"[ERROR] Clone failed: {e}")


def init_submodules() -> None:
    if not Path(".gitmodules").exists():
        return
    print("[INFO] Submodules found. Initialize and update? (y/n)")
    if input().lower() != "y":
        return
    try:
        print("[INFO] Initializing and updating submodules...")
        subprocess.run(
            ["git", "submodule", "update", "--init", "--recursive"],
            check=True,
            capture_output=True,
        )
        print("[INFO] Submodules updated successfully.")
    except subprocess.CalledProcessError as e:
        raise Exception(f"Submodule update failed: {e}")


def confirm_large_repo(size_mb: float) -> bool:
    if size_mb > 100:
        print(f"[WARNING] Repository size is {size_mb:.2f} MB. Continue? (y/n)")
        return input().lower() == "y"
    return True


def main() -> None:
    if len(sys.argv) < 2:
        print("[ERROR] Usage: script.py <repository_url> [--token YOUR_GITHUB_TOKEN]")
        print("Example: script.py owner/repo")
        print("Example: script.py https://github.com/owner/repo")
        print("Example: script.py git@github.com:owner/repo.git")
        print("\nOptional:")
        print("  --token TOKEN    GitHub personal access token (increases rate limit)")
        return
    repo_url = sys.argv[1].strip()
    token = None
    if "--token" in sys.argv:
        token_idx = sys.argv.index("--token") + 1
        if token_idx < len(sys.argv):
            token = sys.argv[token_idx]
    try:
        github_client = get_github_client(token)
        if token:
            print(f"[INFO] Authenticated as: {github_client.get_user().login}")
    except GithubException as e:
        print(f"[ERROR] Authentication failed: {e}")
        return
    try:
        repo = get_repo(repo_url, github_client)
    except (ValueError, Exception) as e:
        print(f"[ERROR] {e}")
        return
    size_mb = get_repo_size(repo)
    if not confirm_large_repo(size_mb):
        print("[INFO] Aborted by user.")
        return
    default_branch = get_default_branch(repo)
    clone_url = build_clone_url(repo)
    try:
        clone_repo(clone_url, default_branch)
    except Exception as e:
        if "not found" in str(e).lower() or "fatal:" in str(e):
            alt_branch = "master" if default_branch == "main" else "main"
            print(f"[WARNING] Branch '{default_branch}' failed, trying '{alt_branch}'...")
            try:
                clone_repo(clone_url, alt_branch)
            except Exception as e2:
                print(f"[ERROR] Clone with both branches failed: {e2}")
                return
        else:
            print(f"[ERROR] {e}")
            return
    try:
        init_submodules()
    except Exception as e:
        print(f"[WARNING] Submodule handling failed: {e}")


if __name__ == "__main__":
    main()
