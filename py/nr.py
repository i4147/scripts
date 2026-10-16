import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

from loguru import logger
import requests

ENV_FILE = Path.home() / ".env"
GITHUB_API_BASE = "https://api.github.com"

logger.remove()
logger.add(
    sys.stderr,
    format="<level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
    level="INFO",
)


def load_github_token() -> str:
    if not ENV_FILE.exists():
        raise FileNotFoundError(f"~/.env not found at {ENV_FILE}. Create it with GITHUB_TOKEN=<your-token>")

    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line.startswith("GITHUB_TOKEN="):
                token = line.split("=", 1)[1].strip("\"'")
                if not token:
                    raise ValueError("GITHUB_TOKEN is empty in ~/.env")
                logger.info("Loaded GITHUB_TOKEN from ~/.env")
                return token

    raise ValueError("GITHUB_TOKEN not found in ~/.env")


def run_git_command(cmd: list[str], cwd: Optional[Path] = None) -> Tuple[str, int]:
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd or Path.cwd(),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip(), result.returncode
    except subprocess.TimeoutExpired:
        logger.error(f"Command timeout: {' '.join(cmd)}")
        raise
    except Exception as e:
        logger.error(f"Git command failed: {e}")
        raise


def is_git_repo(cwd: Path) -> bool:
    git_dir = cwd / ".git"
    return git_dir.exists() and git_dir.is_dir()


def get_remote_url(cwd: Path) -> Optional[str]:
    try:
        url, rc = run_git_command(["git", "config", "--get", "remote.origin.url"], cwd)
        return url if rc == 0 and url else None
    except Exception:
        return None


def get_current_user_login(token: str) -> str:
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    response = requests.get(f"{GITHUB_API_BASE}/user", headers=headers, timeout=10)

    if response.status_code != 200:
        raise requests.RequestException(f"GitHub API error: {response.status_code} - {response.text}")

    login = response.json().get("login")
    logger.info(f"Authenticated as GitHub user: {login}")
    return login


def get_repo_owner(remote_url: str) -> str:

    if "git@github.com:" in remote_url:
        return remote_url.split("git@github.com:")[1].split("/")[0]

    elif "github.com/" in remote_url:
        parts = remote_url.split("github.com/")[1].split("/")
        return parts[0]
    else:
        raise ValueError(f"Unable to parse owner from remote: {remote_url}")


def is_repo_owner(remote_url: str, current_user: str) -> bool:
    owner = get_repo_owner(remote_url)
    is_owner = owner.lower() == current_user.lower()
    logger.info(f"Remote owner: {owner}, Current user: {current_user}, Is owner: {is_owner}")
    return is_owner


def create_github_repo(repo_name: str, token: str, user_login: str, private: bool = False) -> str:
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    payload = {"name": repo_name, "private": private}

    response = requests.post(
        f"{GITHUB_API_BASE}/user/repos",
        headers=headers,
        json=payload,
        timeout=10,
    )

    if response.status_code == 201:
        clone_url = response.json().get("ssh_url")
        logger.info(f"✓ Created GitHub repo: {user_login}/{repo_name}")
        return clone_url
    elif response.status_code == 422:
        raise ValueError(f"Repo '{repo_name}' already exists on GitHub for {user_login}")
    elif response.status_code == 401:
        raise ValueError("Invalid GitHub token (401 Unauthorized)")
    else:
        raise requests.RequestException(f"GitHub API error: {response.status_code} - {response.text}")


def copy_gitignore(cwd: Path) -> None:
    source = Path.home() / ".gitignore"
    target = cwd / ".gitignore"

    if not source.exists():
        logger.warning(f"~/.gitignore not found, skipping copy")
        return

    if target.exists():
        logger.info(".gitignore already exists locally, preserving")
        return

    try:
        target.write_text(source.read_text())
        logger.info(f"✓ Copied .gitignore from ~ → {cwd}")
    except Exception as e:
        logger.error(f"Failed to copy .gitignore: {e}")
        raise


def initialize_git_repo(cwd: Path, remote_url: str) -> None:
    if not is_git_repo(cwd):
        logger.info("Initializing git repository...")
        run_git_command(["git", "init"], cwd)
        run_git_command(["git", "config", "user.email", "your-email@example.com"], cwd)
        run_git_command(["git", "config", "user.name", "Your Name"], cwd)

    existing_url = get_remote_url(cwd)
    if existing_url:
        logger.info(f"Updating remote from {existing_url} → {remote_url}")
        run_git_command(["git", "remote", "remove", "origin"], cwd)

    run_git_command(["git", "remote", "add", "origin", remote_url], cwd)
    logger.info(f"✓ Remote configured: {remote_url}")


def commit_and_push(cwd: Path, token: str) -> None:

    logger.info("Staging files...")
    run_git_command(["git", "add", "."], cwd)

    status, _ = run_git_command(["git", "status", "--porcelain"], cwd)
    if not status:
        logger.info("No changes to commit (working tree clean)")
        return

    logger.info("Creating commit...")
    run_git_command(
        ["git", "commit", "-m", "Initial commit"],
        cwd,
    )

    try:
        run_git_command(["git", "branch", "-M", "main"], cwd)
        logger.info("Branch renamed/created as 'main'")
    except Exception as e:
        logger.warning(f"Could not set branch to main: {e}")

    logger.info("Pushing to origin...")
    try:
        run_git_command(["git", "push", "-u", "origin", "main"], cwd)
        logger.info("✓ Pushed to origin/main")
    except Exception as e:
        logger.error(f"Push failed: {e}")
        logger.info("Troubleshoot: Ensure SSH key is configured or use 'gh auth login'")
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create and push a new GitHub repo from current folder contents.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                      # Repo name = current folder name
  %(prog)s -n my-project        # Repo name = my-project
  %(prog)s -n my-project --private  # Create private repo
        """,
    )
    parser.add_argument(
        "-n",
        "--name",
        type=str,
        default=None,
        help="Repository name (default: current directory name)",
    )
    parser.add_argument(
        "--private",
        action="store_true",
        help="Create as private repo (default: public)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force removal of existing remote without confirmation",
    )

    args = parser.parse_args()

    cwd = Path.cwd()

    try:
        token = load_github_token()
        current_user = get_current_user_login(token)

        repo_name = args.name or cwd.name
        logger.info(f"Target repo name: {repo_name}")

        if not all(c.isalnum() or c in "-_" for c in repo_name):
            logger.error(f"Invalid repo name: {repo_name} (use alphanumeric, -, _)")
            return 1

        copy_gitignore(cwd)

        remote_url = None

        if is_git_repo(cwd):
            logger.info("Existing git repo detected")
            remote_url = get_remote_url(cwd)

            if remote_url:
                logger.info(f"Remote URL found: {remote_url}")

                if is_repo_owner(remote_url, current_user):
                    logger.info(f"✓ You own this repo, proceeding with commit & push")
                else:
                    logger.warning(f"You do NOT own the remote repo")

                    if not args.force:
                        response = input("Remove remote and create new repo in your account? [y/N]: ")
                        if response.lower() != "y":
                            logger.info("Aborted")
                            return 1

                    logger.info("Removing remote...")
                    run_git_command(["git", "remote", "remove", "origin"], cwd)
                    remote_url = None
            else:
                logger.info("Git repo exists but no remote configured")

        if not remote_url:
            logger.info(f"Creating new repo on GitHub: {repo_name}")
            remote_url = create_github_repo(repo_name, token, current_user, args.private)
            initialize_git_repo(cwd, remote_url)

        commit_and_push(cwd, token)

        logger.info(f"✅ Success! Repo available at: https://github.com/{current_user}/{repo_name}")
        return 0

    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        return 130
    except (FileNotFoundError, ValueError) as e:
        logger.error(f"Configuration error: {e}")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
