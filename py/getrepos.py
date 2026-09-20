

import json
import sys
import time
import threading
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def countdown(timeout: int) -> None:
    for remaining in range(timeout, 0, -1):
        sys.stdout.write(f"\rTimeout in {remaining:2d} seconds... ")
        sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write("\r" + " " * 30 + "\r")
    sys.stdout.flush()


def get_repos(username: str, timeout: int = 20) -> list:
    url = f"https://api.github.com/users/{username}/repos"

    
    countdown_thread = threading.Thread(target=countdown, args=(timeout,), daemon=True)
    countdown_thread.start()

    try:
        req = Request(url, headers={"User-Agent": "Python-URLLib"})
        response = urlopen(req, timeout=timeout)
        data = response.read().decode("utf-8")
        repos = json.loads(data)

        if not repos:
            print(f"\nNo public repositories found for user '{username}'.")
            return []

        return repos

    except HTTPError as e:
        if e.code == 404:
            print(f"\nError: User '{username}' not found.")
        else:
            print(f"\nHTTP Error: {e.code} - {e.reason}")
        sys.exit(1)
    except URLError as e:
        print(f"\nError fetching repos: {e.reason}")
        sys.exit(1)
    except TimeoutError:
        print("\nError: Request timed out.")
        sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: script.py <username>")
        sys.exit(1)

    username = sys.argv[1]
    repos = get_repos(username, timeout=20)

    print(f"\nRepositories of '{username}':")
    for repo in repos:
        print(f"- {repo['name']}")

    with Path(f"{username}.txt").open("w", encoding="utf-8") as f:
        for repo in repos:
            f.write(f"- {repo['name']}\n")


if __name__ == "__main__":
    main()
