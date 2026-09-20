from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv
from git import InvalidGitRepositoryError, NoSuchPathError, Repo
from github import Github
from github.Auth import Token

REPO_ROOT = Path.cwd()
DOTENV_PATH = Path.home() / ".env"


def get_dir_name() -> str:
    return os.path.basename(os.getcwd())


def copy_gitignore() -> None:
    src = Path.home() / ".gitignore"
    dst = REPO_ROOT / ".gitignore"

    if src.exists() and not dst.exists():
        shutil.copy2(src, dst)
        print(f"Copied {src} -> {dst}")
    elif dst.exists():
        print(".gitignore already exists in current directory.")
    else:
        print(f"No global .gitignore found at {src}")


def open_repo():
    try:
        return Repo(REPO_ROOT)
    except (InvalidGitRepositoryError, NoSuchPathError):
        return None


def ensure_local_repo() -> Repo:
    repo = open_repo()
    if repo is None:
        print("Initializing git repository...")
        repo = Repo.init(REPO_ROOT)
    else:
        print("Git repository already initialized.")
    return repo


def github_client() -> Github:
    load_dotenv(DOTENV_PATH)
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise SystemExit(f"GITHUB_TOKEN not found in {DOTENV_PATH}")
    return Github(auth=Token(token))


def current_github_login(g: Github) -> str:
    return g.get_user().login


def get_remote_owner_and_name(repo_name: str) -> tuple[str | None, str]:
    if "/" in repo_name:
        owner, name = repo_name.split("/", 1)
        return owner, name
    return None, repo_name


def get_or_create_github_repo(repo_name: str):
    g = github_client()
    me = g.get_user()
    owner_hint, name = get_remote_owner_and_name(repo_name)

    if owner_hint:
        try:
            remote_repo = g.get_repo(repo_name)
        except Exception as e:
            raise SystemExit(f"Could not access remote repo '{repo_name}': {e}")

        if remote_repo.owner.login != me.login:
            print(f"Remote repo is owned by '{remote_repo.owner.login}', not '{me.login}'. Forking...")
            fork = me.create_fork(remote_repo)
            fork_full_name = fork.full_name
            print(f"Created fork: {fork_full_name}")
            g.close()
            return fork_full_name, True

        g.close()
        return remote_repo.full_name, False

    try:
        remote_repo = me.get_repo(name)
        g.close()
        return remote_repo.full_name, False
    except Exception:
        g.close()
        return None, False


def ensure_origin(repo: Repo, repo_name: str) -> None:
    existing = next((r for r in repo.remotes if r.name == "origin"), None)
    g = github_client()
    me = g.get_user()

    if "/" in repo_name:
        remote_repo = g.get_repo(repo_name)
        if remote_repo.owner.login != me.login:
            fork = me.create_fork(remote_repo)
            target_full_name = fork.full_name
        else:
            target_full_name = remote_repo.full_name
    else:
        try:
            remote_repo = me.get_repo(repo_name)
            target_full_name = remote_repo.full_name
        except Exception:
            import subprocess

            cmd = ["gh", "repo", "create", repo_name, "--public", "--source=."]
            print(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"Error: {result.stderr}")
                sys.exit(1)
            target_full_name = f"{me.login}/{repo_name}"

    g.close()

    origin_url = f"git@github.com:{target_full_name}.git"
    if existing:
        if existing.url != origin_url:
            print(f"Updating origin to {origin_url}")
            repo.remotes.origin.set_url(origin_url)
        else:
            print("Remote 'origin' already exists.")
    else:
        repo.create_remote("origin", origin_url)
        print(f"Added remote origin: {origin_url}")


def commit_if_needed(repo: Repo) -> None:
    repo.git.add(all=True)
    if repo.is_dirty(untracked_files=True):
        print("Committing changes...")
        repo.index.commit("initial")
    else:
        print("No changes to commit.")


def push_changes(repo: Repo) -> None:
    branch = repo.active_branch.name if not repo.head.is_detached else "main"
    origin = repo.remote("origin")
    print(f"Pushing branch '{branch}'...")
    try:
        origin.push(refspec=f"{branch}:{branch}")
    except Exception as e:
        msg = str(e)
        if "non-fast-forward" in msg or "fetch first" in msg:
            print("Remote has changes. Pulling first...")
            origin.pull(branch, rebase=True)
            print("Pushing again...")
            origin.push(refspec=f"{branch}:{branch}")
        else:
            raise


def main() -> None:
    repo_name = get_dir_name()
    print(f"Repository name: {repo_name}")

    copy_gitignore()
    repo = ensure_local_repo()
    ensure_origin(repo, repo_name)
    commit_if_needed(repo)
    push_changes(repo)

    print(f"\n✅ Success! Repository '{repo_name}' is now on GitHub or updated there.")
    print(f"View it at: https://github.com/{repo_name}")


if __name__ == "__main__":
    main()
