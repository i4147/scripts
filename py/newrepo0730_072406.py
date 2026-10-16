from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from git import Repo, InvalidGitRepositoryError, NoSuchPathError


def run_gh_repo_create(repo_name: str):
    import subprocess

    cmd = ["gh", "repo", "create", repo_name, "--public", "--source=."]
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
        sys.exit(1)
    return result


def get_dir_name():
    return os.path.basename(os.getcwd())


def copy_gitignore():
    src = Path.home() / ".gitignore"
    dst = Path.cwd() / ".gitignore"

    if src.exists() and not dst.exists():
        shutil.copy2(src, dst)
        print(f"Copied {src} -> {dst}")
    elif dst.exists():
        print(".gitignore already exists in current directory.")
    else:
        print(f"No global .gitignore found at {src}")


def open_repo():
    try:
        return Repo(Path.cwd())
    except (InvalidGitRepositoryError, NoSuchPathError):
        return None


def ensure_repo():
    repo = open_repo()
    if repo is None:
        print("Initializing git repository...")
        repo = Repo.init(Path.cwd())
    else:
        print("Git repository already initialized.")
    return repo


def ensure_origin(repo: Repo, repo_name: str):
    if "origin" in [r.name for r in repo.remotes]:
        print("Remote 'origin' already exists.")
        return

    print(f"Creating GitHub repository '{repo_name}'...")
    run_gh_repo_create(repo_name)

    origin_url = f"git@github.com:{repo_name}.git"
    repo.create_remote("origin", origin_url)
    print(f"Added remote origin: {origin_url}")


def commit_if_needed(repo: Repo):
    repo.git.add(all=True)
    if repo.is_dirty(untracked_files=True):
        print("Committing changes...")
        repo.index.commit("initial")
    else:
        print("No changes to commit.")


def push_changes(repo: Repo):
    branch = repo.active_branch.name if not repo.head.is_detached else "main"
    print(f"Pushing branch '{branch}'...")
    try:
        repo.remote("origin").push(refspec=f"{branch}:{branch}", set_upstream=True)
    except Exception as e:
        msg = str(e)
        if "non-fast-forward" in msg or "fetch first" in msg:
            print("Remote has changes. Pulling first...")
            repo.remote("origin").pull(branch, rebase=True)
            print("Pushing again...")
            repo.remote("origin").push(refspec=f"{branch}:{branch}", set_upstream=True)
        else:
            raise


def main():
    repo_name = get_dir_name()
    print(f"Repository name: {repo_name}")

    copy_gitignore()

    repo = ensure_repo()
    ensure_origin(repo, repo_name)
    commit_if_needed(repo)
    push_changes(repo)

    print(f"\n✅ Success! Repository '{repo_name}' is now on GitHub.")
    print(f"View it at: https://github.com/{repo_name}")


if __name__ == "__main__":
    main()
