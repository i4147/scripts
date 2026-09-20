import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pygit2
from dotenv import load_dotenv
from github import Github, GithubException

SKIP_DIRS = frozenset({"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"})

GITHUB_USERNAME = "unforgivenii147"
ENV_FILE = Path.home() / ".env"
REPO_DIR = Path.cwd()


def load_token() -> str:
    if not ENV_FILE.is_file():
        sys.exit(f"[error] ~/.env not found at {ENV_FILE}")
    load_dotenv(dotenv_path=ENV_FILE)
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        sys.exit("[error] GITHUB_TOKEN not set in ~/.env")
    return token


def get_or_create_github_repo(gh: Github, repo_name: str):
    user = gh.get_user()
    try:
        remote_repo = user.get_repo(repo_name)
        print(f"[info] Found existing GitHub repo: {remote_repo.full_name}")
    except GithubException as exc:
        if exc.status != 404:
            sys.exit(f"[error] GitHub API error: {exc}")
        print(f"[info] Creating new GitHub repo: {GITHUB_USERNAME}/{repo_name}")
        remote_repo = user.create_repo(repo_name, private=False, auto_init=False)
        print(f"[ok] Created: {remote_repo.html_url}")
    return remote_repo


def make_signature() -> pygit2.Signature:
    now = datetime.now(tz=timezone.utc)
    return pygit2.Signature(
        name=GITHUB_USERNAME,
        email=f"{GITHUB_USERNAME}@users.noreply.github.com",
        time=int(now.timestamp()),
        offset=0,
    )


def stage_all(repo: pygit2.Repository) -> bool:
    index = repo.index
    index.read()
    status = repo.status()
    if not status:
        print("[info] Nothing to stage — working tree is clean.")
        return False
    for filepath, flags in status.items():
        deleted = flags & (pygit2.GIT_STATUS_WT_DELETED | pygit2.GIT_STATUS_INDEX_DELETED)
        if deleted:
            try:
                index.remove(filepath)
            except KeyError:
                pass
        else:
            index.add(filepath)
    index.write()
    return True


def commit_all(repo: pygit2.Repository, message: str) -> pygit2.Oid:
    sig = make_signature()
    tree_oid = repo.index.write_tree()
    parents = []
    try:
        head_commit = repo.head.target
        parents = [head_commit]
    except pygit2.GitError:
        pass
    commit_oid = repo.create_commit("refs/heads/main", sig, sig, message, tree_oid, parents)
    print(f"[ok] Committed: {message} ({str(commit_oid)[:7]})")
    return commit_oid


def ensure_remote(repo: pygit2.Repository, remote_url: str) -> pygit2.Remote:
    try:
        remote = repo.remotes["origin"]
        if remote.url != remote_url:
            repo.remotes.set_url("origin", remote_url)
            print(f"[info] Updated remote URL to {remote_url}")
        else:
            print(f"[info] Remote 'origin' already set: {remote_url}")
    except KeyError:
        remote = repo.remotes.create("origin", remote_url)
        print(f"[ok] Added remote 'origin': {remote_url}")
    return remote


def push_to_remote(repo: pygit2.Repository, token: str) -> None:
    remote = repo.remotes["origin"]
    callbacks = pygit2.RemoteCallbacks(credentials=pygit2.UserpassCredentials(token, "x-oauth-basic"))
    refspec = "refs/heads/main:refs/heads/main"
    remote.push([refspec], callbacks=callbacks)
    print("[ok] Pushed to origin/main.")


def main() -> None:
    token = load_token()
    gh = Github(token)
    repo_name = REPO_DIR.name
    print(f"[info] Working directory : {REPO_DIR}")
    print(f"[info] Repo name         : {repo_name}")
    git_dir = REPO_DIR / ".git"
    is_new_local_repo = not git_dir.exists()
    if is_new_local_repo:
        print("[info] No .git found — initialising new local repo.")
        repo = pygit2.init_repository(str(REPO_DIR), initial_head="main")
    else:
        print("[info] Existing local git repo detected.")
        repo = pygit2.Repository(str(REPO_DIR))
    has_changes = stage_all(repo)
    if has_changes:
        if is_new_local_repo:
            msg = "Initial commit"
        else:
            msg = f"Update {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        commit_all(repo, msg)
    else:
        try:
            repo.head
        except pygit2.GitError:
            print("[warn] Repo has no commits and nothing to stage. Exiting.")
            return
    remote_repo = get_or_create_github_repo(gh, repo_name)
    remote_url = remote_repo.clone_url
    has_origin = "origin" in [r.name for r in repo.remotes]
    if not has_origin:
        ensure_remote(repo, remote_url)
    else:
        ensure_remote(repo, remote_url)
    push_to_remote(repo, token)
    print(f"\n[done] {remote_repo.html_url}")


if __name__ == "__main__":
    main()
