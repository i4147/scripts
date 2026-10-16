import os
import sys

import requests
from loguru import logger


def get_repo_size_mb(repo_url_or_name: str):
    if "/" not in repo_url_or_name:
        logger.info("Error: Please provide the repository in 'user/repo_name' or full URL format.")
        return None
    if "https://github.com/" in repo_url_or_name:
        repo_url = repo_url_or_name
    else:
        repo_url = f"https://github.com/{repo_url_or_name}"
    try:
        parts = repo_url.rstrip("/").split("/")
        owner = parts[-2]
        repo_name = parts[-1]
    except IndexError:
        logger.info(f"Error: Could not parse repository name from: {repo_url}")
        return None
    api_url = f"https://api.github.com/repos/{owner}/{repo_name}"
    try:
        response = requests.get(api_url, timeout=300)
        response.raise_for_status()
        repo_data = response.json()
        size_kb = repo_data.get("size")
        if size_kb is not None:
            logger.info(f"{api_url}:{size_kb}")
            return size_kb / 1024
        else:
            logger.info(f"Error: Size information not found for {owner}/{repo_name}")
            return None
    except requests.exceptions.RequestException as e:
        logger.info(f"Error fetching repository data for {owner}/{repo_name}: {e}")
        return None
    except KeyError:
        logger.info(f"Error parsing response for {owner}/{repo_name}.")
        return None


def update_repos_file(filename: str = "repos.txt") -> None:
    if not os.path.exists(filename):
        logger.info(f"Error: File '{filename}' not found.")
        return
    updated_lines = []
    try:
        with open(filename, "r") as f:
            for line in f:
                repo_name = line.strip()
                if not repo_name:
                    continue
                size_mb = get_repo_size_mb(repo_name)
                if size_mb is not None:
                    updated_lines.append(f"{repo_name} (Size: {size_mb:.2f} MB)")
                else:
                    updated_lines.append(repo_name)
    except IOError as e:
        logger.info(f"Error reading file '{filename}': {e}")
        return
    try:
        with open(filename, "w") as f:
            for line in updated_lines:
                f.write(line + "\n")
        logger.info(f"Successfully updated '{filename}' with repository sizes.")
    except IOError as e:
        logger.info(f"Error writing to file '{filename}': {e}")


if __name__ == "__main__":
    if not os.path.exists("repos.txt"):
        sys.exit(0)
    update_repos_file("repos.txt")
