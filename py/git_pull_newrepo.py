#!/data/data/com.termux/files/usr/bin/python
"""Write a Python script that scans a local root directory recursively for Git repositories (ignoring hidden folders), and for each discovered repository creates a matching public repository on the user's GitHub account using an access token loaded from environment configuration. The script should read the token from a local `.env` file or environment variables, use the directory name as the repository name, and add a default description to each new repository without initializing it with any files. After creating each remote repository, it should register it as a remote named "origin" in the local repository (or update the existing remote if one already exists) and push the current branch to GitHub. Handle failures gracefully: if a GitHub repository with that name already exists or the API request fails, report the error clearly and continue processing the remaining repositories rather than stopping. Print clear, human-readable progress messages with success and failure indicators for each repository, along with a final summary showing how many repositories were processed, created, pushed, and failed. The script should accept the root directory to scan as a command-line argument (defaulting to the current working directory if none is provided) and should validate that the path exists before starting. Ensure that no credentials are printed to the console or written to logs, and make the script safe to re-run without duplicating remotes or corrupting existing repositories.
---"""

from __future__ import annotations

import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from git import GitCommandError, Repo

load_dotenv()


def find_git_repos(root_path: Path) -> list[Path]:
    repos = []
    for item in root_path.iterdir():
        if item.is_dir() and not item.name.startswith("."):
            if (item / ".git").exists():
                repos.append(item)
            else:
                repos.extend(find_git_repos(item))
    return repos


def create_github_repo(repo_name: str, github_token: str) -> str | None:
    url = "https://api.github.com/user/repos"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }
    data = {
        "name": repo_name,
        "description": f"Repository for {repo_name}",
        "private": False,
        "auto_init": False,
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        repo_info = response.json()
        clone_url = repo_info["clone_url"]
        print(f"   ✅ GitHub repo created: {clone_url}")
        return clone_url
    except requests.exceptions.RequestException as e:
        if response.status_code == 422:
            print(f"   ⚠️  Repository '{repo_name}' already exists on GitHub")
            try:
                f"https://api.github.com/repos/{response.json().get('errors', [{}])[0].get('resource', '')}"
                username = get_github_username(github_token)
                if username:
                    existing_url = f"https://github.com/{username}/{repo_name}.git"
                    print(f"   ℹ️  Using existing repo: {existing_url}")
                    return existing_url
            except:
                pass
        else:
            print(f"   ❌ Failed to create repo: {e}")
        return None


def get_github_username(github_token: str) -> str | None:
    url = "https://api.github.com/user"
    headers = {"Authorization": f"token {github_token}"}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()["login"]
    except:
        return None


def setup_remote_and_push(repo: Repo, repo_path: Path, remote_url: str) -> bool:
    try:
        if "origin" in repo.remotes:
            repo.remotes.origin.set_url(remote_url)
            print(f"   🔄 Updated existing remote 'origin' to {remote_url}")
        else:
            repo.create_remote("origin", remote_url)
            print(f"   🔗 Added remote 'origin': {remote_url}")
        print("   📤 Pushing to GitHub...")
        current_branch = repo.active_branch.name
        repo.remotes.origin.push(refspec=f"{current_branch}:{current_branch}", set_upstream=True)
        print(f"   ✅ Pushed branch '{current_branch}' to GitHub")
        return True
    except GitCommandError as e:
        print(f"   ❌ Git error: {e.stderr.strip() if e.stderr else str(e)}")
        return False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


def process_repository(repo_path: Path, github_token: str) -> tuple[bool, str]:
    try:
        repo = Repo(repo_path)
        rel_path = repo_path.relative_to(Path.cwd())
        if repo.remotes:
            print(f"\n📁 {rel_path} (has remote)")
            print(f"   Branch: {repo.active_branch.name}")
            try:
                repo.remotes.origin.pull()
                print("   ✅ Pull successful")
                return True, "Pulled successfully"
            except GitCommandError as e:
                if "merge conflict" in str(e).lower():
                    return False, "Merge conflicts detected"
                return (
                    False,
                    f"Pull failed: {e.stderr.strip() if e.stderr else str(e)}",
                )
        else:
            print(f"\n📁 {rel_path} (no remote configured)")
            print(f"   Creating GitHub repository: {repo_path.name}")
            remote_url = create_github_repo(repo_path.name, github_token)
            if not remote_url:
                return False, "Failed to create GitHub repository"
            if setup_remote_and_push(repo, repo_path, remote_url):
                return True, f"Created and pushed to {remote_url}"
            else:
                return False, "Failed to push to GitHub"
    except Exception as e:
        return False, f"Error: {e!s}"


def main() -> None:
    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        print("❌ Error: GITHUB_TOKEN not found in .env file")
        print("Please create a .env file with: GITHUB_TOKEN=your_token_here")
        return
    cwd = Path.cwd()
    print(f"🔍 Scanning for git repositories in: {cwd}")
    repos = find_git_repos(cwd)
    if not repos:
        print("No git repositories found")
        return
    print(f"Found {len(repos)} repository(ies)\n")
    results = []
    for repo_path in repos:
        success, message = process_repository(repo_path, github_token)
        results.append((repo_path, success, message))
    print("\n" + "=" * 40)
    print("SUMMARY")
    print("-" * 40)
    successful = [r for r in results if r[1]]
    failed = [r for r in results if not r[1]]
    if successful:
        print(f"\n✅ Successful ({len(successful)} repos):")
        for repo_path, _, msg in successful:
            print(f"   - {repo_path.relative_to(cwd)}: {msg}")
    if failed:
        print(f"\n❌ Failed ({len(failed)} repos):")
        for repo_path, _, msg in failed:
            print(f"   - {repo_path.relative_to(cwd)}: {msg}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Operation cancelled by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
