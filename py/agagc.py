

from subprocess import CompletedProcess
import subprocess
import sys
from datetime import datetime


def run(cmd: list[str]) -> CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True)


def main() -> None:
    try:
        run(["git", "--version"])
    except FileNotFoundError:
        print("git not found. Please install git.", file=sys.stderr)
        sys.exit(1)
    r = run(["git", "rev-parse", "--is-inside-work-tree"])
    if r.returncode != 0 or r.stdout.strip() != "true":
        print("Not inside a git repository.", file=sys.stderr)
        sys.exit(1)
    r = run(["git", "add", "."])
    if r.returncode != 0:
        print("git add failed:", r.stderr.strip(), file=sys.stderr)
        sys.exit(r.returncode)
    check = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if check.returncode == 0:
        print("No changes to commit.")
        return
    msg = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    r = run(["git", "commit", "-m", msg])
    if r.returncode == 0:
        print(f'Committed with message: "{msg}"')
        if r.stdout.strip():
            print(r.stdout.strip())
    else:
        print("git commit failed:", r.stderr.strip(), file=sys.stderr)
        sys.exit(r.returncode)


if __name__ == "__main__":
    main()
