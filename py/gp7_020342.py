import subprocess
import sys
from datetime import datetime
from pathlib import Path


def run_git_cmd(cmd: list[str], capture: bool = False) -> str:
    try:
        result = subprocess.run(cmd, capture_output=capture, text=True, check=True)
        return result.stdout.strip() if capture else ""
    except subprocess.CalledProcessError as e:
        print(f"Error running {' '.join(cmd)}: {e.stderr or e}", file=sys.stderr)
        sys.exit(e.returncode or 1)
    except FileNotFoundError:
        print("Git executable not found. Ensure git is installed.", file=sys.stderr)
        sys.exit(127)


def symlink_global_gitignore() -> None:
    home_gitignore = Path.home() / ".gitignore"
    local_gitignore = Path(".gitignore")
    if not home_gitignore.exists():
        return
    if local_gitignore.exists() or local_gitignore.is_symlink():
        return
    try:
        local_gitignore.symlink_to(home_gitignore)
        print(f"Symlinked {home_gitignore} → {local_gitignore}")
    except Exception as e:
        print(f"Failed to create symlink: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    run_git_cmd(["git", "rev-parse", "--is-inside-work-tree"], capture=True)
    symlink_global_gitignore()
    run_git_cmd(["git", "add", "-A"])
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    commit_msg = f"Auto-commit at {now}"
    run_git_cmd(["git", "commit", "-m", commit_msg])
    branch = run_git_cmd(["git", "branch", "--show-current"], capture=True)
    if not branch:
        print("Error: Could not detect current branch (detached HEAD?).", file=sys.stderr)
        sys.exit(1)
    run_git_cmd(["git", "push", "origin", branch])
    print(f"Pushed to origin/{branch} with message: {commit_msg}")


if __name__ == "__main__":
    main()
