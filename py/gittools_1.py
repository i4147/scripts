#!/data/data/com.termux/files/usr/bin/python
from __future__ import annotations
import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import traceback
import zipfile
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib.parse import urlparse
import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()
err_console = Console(stderr=True)
DEFAULT_GITHUB_USERNAME = "i4147"
DEFAULT_GIT_EMAIL = "adnanonagh@gmail.com"
DEFAULT_GIT_USER = "i4147"
DEFAULT_ENV_FILE = Path.home() / ".env"
DEFAULT_GLOBAL_GITIGNORE = Path.home() / ".gitignore"
DEFAULT_DESCRIPTION = "created with python"
DEFAULT_BRANCH = "main"
DEFAULT_API_PUSH_COMMIT_MESSAGE = "Update files"
DEFAULT_GH_CREATE_COMMIT_MESSAGE = "initial"
DEFAULT_GH_CLI_COMMIT_MESSAGE = "initial"
BACKEND_CHOICES = [
    "subprocess",
    "gitpython",
    "rest",
    "pygithub",
    "githubpython",
    "dulwich",
    "libgit2",
]
MAINT_BACKEND_CHOICES = ["subprocess", "gitpython", "libgit2", "dulwich", "pygithub", "gh", "typer"]


def info(msg: str) -> None:
    console.print(f"[cyan][INFO][/cyan] {msg}")


def warn(msg: str) -> None:
    err_console.print(f"[yellow][WARN][/yellow] {msg}")


def err(msg: str) -> None:
    err_console.print(f"[red][ERR][/red] {msg}")


def ok(msg: str) -> None:
    console.print(f"[green]✓[/green] {msg}")


def parse_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    try:
        with path.open() as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    key, _, value = line.partition("=")
                    env[key.strip()] = value.strip()
    except FileNotFoundError:
        pass
    except Exception as exc:
        err(f"Error reading {path}: {exc}")
    return env


def get_github_token(env_file: Path | None = None) -> Optional[str]:
    env_file = env_file or DEFAULT_ENV_FILE
    env = parse_env_file(env_file)
    return env.get("GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")


def run_cli(cmd: Sequence[str], cwd: Path | None = None, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(cmd),
        cwd=str(cwd) if cwd else None,
        check=check,
        capture_output=True,
        text=True,
    )


class GitBackend(ABC):
    @abstractmethod
    def is_git_repo(self, path: Path) -> bool: ...
    @abstractmethod
    def init_repo(self, path: Path) -> None: ...
    @abstractmethod
    def config_user(self, path: Path, name: str, email: str) -> None: ...
    @abstractmethod
    def add_all(self, path: Path) -> None: ...
    @abstractmethod
    def commit(self, path: Path, message: str) -> bool: ...
    @abstractmethod
    def is_dirty(self, path: Path) -> bool: ...
    @abstractmethod
    def get_remote_url(self, path: Path, name: str = "origin") -> Optional[str]: ...
    @abstractmethod
    def add_remote(self, path: Path, name: str, url: str) -> None: ...
    @abstractmethod
    def set_remote_url(self, path: Path, name: str, url: str) -> None: ...
    @abstractmethod
    def remove_remote(self, path: Path, name: str) -> None: ...
    @abstractmethod
    def push(self, path: Path, remote: str, branch: str, set_upstream: bool = True) -> None: ...
    @abstractmethod
    def current_branch(self, path: Path) -> str: ...
    @abstractmethod
    def rename_branch(self, path: Path, new_name: str) -> None: ...


class SubprocessGit(GitBackend):
    def _run(self, cmd: Sequence[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
        return run_cli(cmd, cwd=cwd, check=check)

    def is_git_repo(self, path: Path) -> bool:
        return self._run(["git", "rev-parse", "--git-dir"], path, check=False).returncode == 0

    def init_repo(self, path: Path) -> None:
        self._run(["git", "init"], path)

    def config_user(self, path: Path, name: str, email: str) -> None:
        self._run(["git", "config", "user.name", name], path, check=False)
        self._run(["git", "config", "user.email", email], path, check=False)

    def add_all(self, path: Path) -> None:
        self._run(["git", "add", "-A"], path)

    def commit(self, path: Path, message: str) -> bool:
        r = self._run(["git", "commit", "-m", message], path, check=False)
        return r.returncode == 0

    def is_dirty(self, path: Path) -> bool:
        r = self._run(["git", "status", "--porcelain"], path, check=False)
        return bool(r.stdout.strip())

    def get_remote_url(self, path: Path, name: str = "origin") -> Optional[str]:
        r = self._run(["git", "remote", "get-url", name], path, check=False)
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None

    def add_remote(self, path: Path, name: str, url: str) -> None:
        self._run(["git", "remote", "add", name, url], path)

    def set_remote_url(self, path: Path, name: str, url: str) -> None:
        self._run(["git", "remote", "set-url", name, url], path)

    def remove_remote(self, path: Path, name: str) -> None:
        self._run(["git", "remote", "remove", name], path, check=False)

    def push(self, path: Path, remote: str, branch: str, set_upstream: bool = True) -> None:
        cmd = ["git", "push"]
        if set_upstream:
            cmd.append("-u")
        cmd += [remote, branch]
        r = self._run(cmd, path, check=False)
        if r.returncode != 0:
            raise RuntimeError(f"Push failed: {r.stderr.strip() or r.stdout.strip()}")

    def current_branch(self, path: Path) -> str:
        r = self._run(["git", "branch", "--show-current"], path, check=False)
        return r.stdout.strip() or "main"

    def rename_branch(self, path: Path, new_name: str) -> None:
        self._run(["git", "branch", "-M", new_name], path, check=False)


class GitPythonGit(GitBackend):
    def _repo(self, path: Path) -> Any:
        from git import InvalidGitRepositoryError, Repo

        try:
            return Repo(str(path))
        except InvalidGitRepositoryError:
            return None

    def is_git_repo(self, path: Path) -> bool:
        return self._repo(path) is not None

    def init_repo(self, path: Path) -> None:
        from git import Repo

        Repo.init(str(path))

    def config_user(self, path: Path, name: str, email: str) -> None:
        repo = self._repo(path)
        if repo:
            with repo.config_writer() as cw:
                cw.set_value("user", "name", name)
                cw.set_value("user", "email", email)

    def add_all(self, path: Path) -> None:
        repo = self._repo(path)
        if repo:
            repo.git.add(all=True)

    def commit(self, path: Path, message: str) -> bool:
        repo = self._repo(path)
        if not repo or not repo.is_dirty(untracked_files=True):
            return False
        repo.index.commit(message)
        return True

    def is_dirty(self, path: Path) -> bool:
        repo = self._repo(path)
        return bool(repo and repo.is_dirty(untracked_files=True))

    def get_remote_url(self, path: Path, name: str = "origin") -> Optional[str]:
        repo = self._repo(path)
        if not repo:
            return None
        try:
            return repo.remote(name).url
        except ValueError:
            return None

    def add_remote(self, path: Path, name: str, url: str) -> None:
        repo = self._repo(path)
        if repo:
            repo.create_remote(name, url)

    def set_remote_url(self, path: Path, name: str, url: str) -> None:
        repo = self._repo(path)
        if repo:
            remote = repo.remote(name)
            with remote.config_writer as cw:
                cw.set_value("url", url)

    def remove_remote(self, path: Path, name: str) -> None:
        repo = self._repo(path)
        if repo:
            with contextlib.suppress(Exception):
                repo.delete_remote(name)

    def push(self, path: Path, remote: str, branch: str, set_upstream: bool = True) -> None:
        repo = self._repo(path)
        if not repo:
            raise RuntimeError("Not a git repository")
        kwargs = {"set_upstream": True} if set_upstream else {}
        repo.remote(remote).push(refspec=f"{branch}:{branch}", **kwargs)

    def current_branch(self, path: Path) -> str:
        repo = self._repo(path)
        if not repo or repo.head.is_detached:
            return "main"
        return repo.active_branch.name

    def rename_branch(self, path: Path, new_name: str) -> None:
        repo = self._repo(path)
        if repo:
            repo.git.branch("-M", new_name)


class DulwichGit(GitBackend):
    @staticmethod
    def _dulwich() -> Any:
        try:
            from dulwich import porcelain
            from dulwich.repo import Repo

            return porcelain, Repo
        except ImportError as exc:
            raise SystemExit("dulwich backend requires `pip install dulwich`") from exc

    def is_git_repo(self, path: Path) -> bool:
        _, Repo = self._dulwich()
        try:
            Repo(str(path))
            return True
        except Exception:
            return False

    def init_repo(self, path: Path) -> None:
        porcelain, _ = self._dulwich()
        porcelain.init(str(path))

    def config_user(self, path: Path, name: str, email: str) -> None:
        _, Repo = self._dulwich()
        repo = Repo(str(path))
        cfg = repo.get_config()
        cfg.set((b"user",), b"name", name.encode())
        cfg.set((b"user",), b"email", email.encode())
        cfg.write_to_path()

    def add_all(self, path: Path) -> None:
        porcelain, _ = self._dulwich()
        porcelain.add(str(path))

    def commit(self, path: Path, message: str) -> bool:
        porcelain, Repo = self._dulwich()
        repo = Repo(str(path))
        status = porcelain.status(repo)
        if not (status.untracked or status.unstaged or status.staged):
            return False
        porcelain.commit(str(path), message=message.encode(), author=None, committer=None)
        return True

    def is_dirty(self, path: Path) -> bool:
        porcelain, Repo = self._dulwich()
        repo = Repo(str(path))
        s = porcelain.status(repo)
        return bool(s.untracked or s.unstaged or s.staged)

    def get_remote_url(self, path: Path, name: str = "origin") -> Optional[str]:
        _, Repo = self._dulwich()
        repo = Repo(str(path))
        try:
            return repo.get_config().get((b"remote", name.encode()), b"url").decode()
        except KeyError:
            return None

    def add_remote(self, path: Path, name: str, url: str) -> None:
        _, Repo = self._dulwich()
        repo = Repo(str(path))
        cfg = repo.get_config()
        cfg.set((b"remote", name.encode()), b"url", url.encode())
        cfg.set((b"remote", name.encode()), b"fetch", f"+refs/heads/*:refs/remotes/{name}/*".encode())
        cfg.write_to_path()

    def set_remote_url(self, path: Path, name: str, url: str) -> None:
        _, Repo = self._dulwich()
        repo = Repo(str(path))
        cfg = repo.get_config()
        cfg.set((b"remote", name.encode()), b"url", url.encode())
        cfg.write_to_path()

    def remove_remote(self, path: Path, name: str) -> None:
        _, Repo = self._dulwich()
        repo = Repo(str(path))
        cfg = repo.get_config()
        try:
            cfg.remove_section((b"remote", name.encode()))
            cfg.write_to_path()
        except KeyError:
            pass

    def push(self, path: Path, remote: str, branch: str, set_upstream: bool = True) -> None:
        porcelain, _ = self._dulwich()
        porcelain.push(str(path), remote, f"refs/heads/{branch}:refs/heads/{branch}")

    def current_branch(self, path: Path) -> str:
        _, Repo = self._dulwich()
        repo = Repo(str(path))
        try:
            ref = repo.refs.read_ref(b"HEAD")
            prefix = b"ref: refs/heads/"
            if ref and ref.startswith(prefix):
                return ref[len(prefix) :].decode()
        except Exception:
            pass
        return "main"

    def rename_branch(self, path: Path, new_name: str) -> None:
        _, Repo = self._dulwich()
        repo = Repo(str(path))
        current = self.current_branch(path)
        if current == new_name:
            return
        src = f"refs/heads/{current}".encode()
        dst = f"refs/heads/{new_name}".encode()
        sha = repo.refs.read_ref(src)
        if sha is None:
            return
        repo.refs[dst] = sha
        with contextlib.suppress(Exception):
            repo.refs.remove_if_equals(src, sha)
        repo.refs.set_symbolic_ref(b"HEAD", dst)


class Pygit2Git(GitBackend):
    @staticmethod
    def _pg() -> Any:
        try:
            import pygit2

            return pygit2
        except ImportError as exc:
            raise SystemExit("libgit2 backend requires `pip install pygit2`") from exc

    def _repo(self, path: Path) -> Any:
        pg = self._pg()
        try:
            return pg.Repository(str(path))
        except Exception:
            return None

    def is_git_repo(self, path: Path) -> bool:
        return self._repo(path) is not None

    def init_repo(self, path: Path) -> None:
        pg = self._pg()
        pg.init_repository(str(path))

    def config_user(self, path: Path, name: str, email: str) -> None:
        repo = self._repo(path)
        if repo:
            repo.config["user.name"] = name
            repo.config["user.email"] = email

    def add_all(self, path: Path) -> None:
        repo = self._repo(path)
        if repo:
            repo.index.add_all()
            repo.index.write()

    def commit(self, path: Path, message: str) -> bool:
        repo = self._repo(path)
        if not repo:
            return False
        if not repo.status():
            return False
        tree = repo.index.write_tree()
        parents = [repo.head.target] if not repo.head_is_unborn else []
        sig = repo.default_signature
        repo.create_commit("HEAD", sig, sig, message, tree, parents)
        return True

    def is_dirty(self, path: Path) -> bool:
        repo = self._repo(path)
        return bool(repo and repo.status())

    def get_remote_url(self, path: Path, name: str = "origin") -> Optional[str]:
        repo = self._repo(path)
        if not repo:
            return None
        try:
            return repo.remotes[name].url
        except KeyError:
            return None

    def add_remote(self, path: Path, name: str, url: str) -> None:
        repo = self._repo(path)
        if repo:
            try:
                repo.remotes.create(name, url)
            except Exception:
                repo.remotes[name].url = url

    def set_remote_url(self, path: Path, name: str, url: str) -> None:
        repo = self._repo(path)
        if repo:
            try:
                repo.remotes[name].url = url
            except KeyError:
                repo.remotes.create(name, url)

    def remove_remote(self, path: Path, name: str) -> None:
        repo = self._repo(path)
        if repo:
            with contextlib.suppress(Exception):
                repo.remotes.delete(name)

    def push(self, path: Path, remote: str, branch: str, set_upstream: bool = True) -> None:
        raise NotImplementedError("push via pygit2 requires credential callbacks; use 'subprocess' backend")

    def current_branch(self, path: Path) -> str:
        repo = self._repo(path)
        if not repo:
            return "main"
        try:
            return repo.head.shorthand
        except Exception:
            return "main"

    def rename_branch(self, path: Path, new_name: str) -> None:
        repo = self._repo(path)
        if not repo:
            return
        current = self.current_branch(path)
        if current == new_name:
            return
        branch = repo.branches.get(current)
        if branch:
            branch.rename(new_name)


class GitHubBackend(ABC):
    @abstractmethod
    def repo_exists(self, owner: str, name: str) -> bool: ...
    @abstractmethod
    def create_repo(
        self,
        name: str,
        description: str = "",
        private: bool = False,
        auto_init: bool = False,
        owner: Optional[str] = None,
    ) -> Optional[dict]: ...


class GhCliGitHub(GitHubBackend):
    def __init__(self, username: Optional[str] = None) -> None:
        self.username = username

    def repo_exists(self, owner: str, name: str) -> bool:
        r = run_cli(["gh", "repo", "view", f"{owner}/{name}"])
        return r.returncode == 0

    def create_repo(
        self,
        name: str,
        description: str = "",
        private: bool = False,
        auto_init: bool = False,
        owner: Optional[str] = None,
    ) -> Optional[dict]:
        cmd = ["gh", "repo", "create", name, "--source=.", "--remote=origin", "--private" if private else "--public"]
        if description:
            cmd += ["--description", description]
        r = run_cli(cmd)
        if r.returncode != 0:
            if owner and self.repo_exists(owner, name):
                return {"ssh_url": f"git@github.com:{owner}/{name}.git"}
            return None
        return {"name": name, "ssh_url": f"git@github.com:{owner}/{name}.git"}


class RestGitHub(GitHubBackend):
    def __init__(self, token: str, username: Optional[str] = None) -> None:
        self.token = token
        self.username = username

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"token {self.token}", "Accept": "application/vnd.github.v3+json"}

    def repo_exists(self, owner: str, name: str) -> bool:
        import requests

        r = requests.get(f"https://api.github.com/repos/{owner}/{name}", headers=self._headers())
        return r.status_code == 200

    def create_repo(
        self,
        name: str,
        description: str = "",
        private: bool = False,
        auto_init: bool = False,
        owner: Optional[str] = None,
    ) -> Optional[dict]:
        import requests

        payload = {"name": name, "description": description, "private": private, "auto_init": auto_init}
        r = requests.post("https://api.github.com/user/repos", headers=self._headers(), json=payload)
        if r.status_code == 201:
            return r.json()
        if r.status_code == 422 and owner:
            return {"ssh_url": f"git@github.com:{owner}/{name}.git"}
        with contextlib.suppress(Exception):
            warn(f"REST create failed ({r.status_code}): {r.json().get('message')}")
        return None


class PyGithubGitHub(GitHubBackend):
    def __init__(self, token: str, username: Optional[str] = None) -> None:
        try:
            from github import Github
            from github.Auth import Token
        except ImportError as exc:
            raise SystemExit("pygithub backend requires `pip install PyGithub`") from exc
        self.client = Github(auth=Token(token))
        self.username = username

    def repo_exists(self, owner: str, name: str) -> bool:
        try:
            user = self.client.get_user(owner) if owner else self.client.get_user()
            user.get_repo(name)
            return True
        except Exception:
            return False

    def create_repo(
        self,
        name: str,
        description: str = "",
        private: bool = False,
        auto_init: bool = False,
        owner: Optional[str] = None,
    ) -> Optional[dict]:
        try:
            user = self.client.get_user(owner) if owner else self.client.get_user()
            repo = user.create_repo(name=name, description=description, private=private, auto_init=auto_init)
            return {"name": repo.name, "html_url": repo.html_url, "clone_url": repo.clone_url, "ssh_url": repo.ssh_url}
        except Exception as exc:
            if "already exists" in str(exc).lower() and owner:
                return {"ssh_url": f"git@github.com:{owner}/{name}.git"}
            warn(f"PyGithub create failed: {exc}")
            return None


class Github3GitHub(GitHubBackend):
    def __init__(self, token: str, username: Optional[str] = None) -> None:
        try:
            import github3
        except ImportError as exc:
            raise SystemExit("githubpython backend requires `pip install github3.py`") from exc
        self.client = github3.login(token=token)
        self.username = username

    def repo_exists(self, owner: str, name: str) -> bool:
        try:
            return self.client.repository(owner, name) is not None
        except Exception:
            return False

    def create_repo(
        self,
        name: str,
        description: str = "",
        private: bool = False,
        auto_init: bool = False,
        owner: Optional[str] = None,
    ) -> Optional[dict]:
        try:
            repo = self.client.create_repo(name, description=description or None, private=private, auto_init=auto_init)
            return {"name": repo.name, "html_url": repo.html_url, "clone_url": repo.clone_url, "ssh_url": repo.ssh_url}
        except Exception as exc:
            if "already exists" in str(exc).lower() and owner:
                return {"ssh_url": f"git@github.com:{owner}/{name}.git"}
            warn(f"github3.py create failed: {exc}")
            return None


@dataclass
class Backend:
    name: str
    git: GitBackend
    github: GitHubBackend


def make_backend(name: str, token: Optional[str], username: Optional[str]) -> Backend:
    if name == "subprocess":
        return Backend(name, SubprocessGit(), GhCliGitHub(username))
    if name == "gitpython":
        return Backend(name, GitPythonGit(), GhCliGitHub(username))
    if name == "rest":
        if not token:
            raise SystemExit("Backend 'rest' requires GITHUB_TOKEN.")
        return Backend(name, SubprocessGit(), RestGitHub(token, username))
    if name == "pygithub":
        if not token:
            raise SystemExit("Backend 'pygithub' requires GITHUB_TOKEN.")
        return Backend(name, SubprocessGit(), PyGithubGitHub(token, username))
    if name == "githubpython":
        if not token:
            raise SystemExit("Backend 'githubpython' requires GITHUB_TOKEN.")
        return Backend(name, SubprocessGit(), Github3GitHub(token, username))
    if name == "dulwich":
        return Backend(name, DulwichGit(), GhCliGitHub(username))
    if name == "libgit2":
        return Backend(name, Pygit2Git(), GhCliGitHub(username))
    raise SystemExit(f"Unknown backend: {name}")


def resolve_backend(backend_name: str, env_file: Path, username: Optional[str]) -> Backend:
    token = get_github_token(env_file)
    return make_backend(backend_name, token, username)


@dataclass
class CommitInfo:
    sha: str
    subject: str
    timestamp: int
    parents: list[str] = field(default_factory=list)

    @property
    def short(self) -> str:
        return self.sha[:8]

    @property
    def date(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp, tz=timezone.utc)


class MaintenanceGit:
    def __init__(self, repo: Path, backend: str = "subprocess") -> None:
        self.repo = Path(repo).resolve()
        self.backend = backend
        self._use_gitpython = backend == "gitpython"
        self._gitpython_repo: Any = None
        if self._use_gitpython:
            try:
                from git import Repo

                self._gitpython_repo = Repo(str(self.repo))
            except Exception:
                self._gitpython_repo = None

    def _run(self, *args: str, check: bool = True, input: Optional[str] = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            input=input,
            check=check,
        )

    def _git(self, *args: str) -> str:
        return self._run(*args).stdout.strip()

    def is_repo(self) -> bool:
        r = self._run("rev-parse", "--is-inside-work-tree", check=False)
        return r.returncode == 0 and r.stdout.strip() == "true"

    def rev_parse(self, *args: str) -> str:
        return self._git("rev-parse", *args)

    def head_sha(self) -> str:
        return self.rev_parse("HEAD")

    def current_branch(self) -> Optional[str]:
        r = self._run("symbolic-ref", "--short", "-q", "HEAD", check=False)
        return r.stdout.strip() or None

    def is_dirty(self, untracked: bool = True) -> bool:
        args = ["status", "--porcelain"]
        if not untracked:
            args.append("--untracked-files=no")
        return bool(self._run(*args, check=False).stdout.strip())

    def status_porcelain(self) -> list[str]:
        return self._run("status", "--porcelain", check=False).stdout.splitlines()

    def log(self, *, ref: str = "HEAD", n: Optional[int] = None, reverse: bool = False) -> list[CommitInfo]:
        args = ["log", "--format=%H%x00%s%x00%ct%x00%P"]
        if n:
            args.append(f"-n{n}")
        if reverse:
            args.append("--reverse")
        args.append(ref)
        out = self._run(*args, check=False).stdout
        commits: list[CommitInfo] = []
        for line in out.splitlines():
            if not line.strip():
                continue
            parts = line.split(" \x00")
            if len(parts) < 1:
                parts = line.split("\x00")
            if len(parts) < 4:
                parts = line.split(" ")
            if len(parts) < 4:
                continue
            try:
                commits.append(
                    CommitInfo(
                        sha=parts[0],
                        subject=parts[1],
                        timestamp=int(parts[2]),
                        parents=parts[3].split() if parts[3] else [],
                    )
                )
            except ValueError:
                continue
        return commits

    def checkout(self, ref: str) -> None:
        self._git("checkout", ref)

    def reset(self, ref: str, mode: str = "hard") -> None:
        self._git("reset", f"--{mode}", ref)

    def cherry_pick(self, sha: str, allow_empty: bool = True) -> None:
        args = ["cherry-pick"]
        if allow_empty:
            args.append("--allow-empty")
        args.append(sha)
        self._git(*args)

    def create_branch(self, name: str, start: Optional[str] = None) -> None:
        args = ["branch", name]
        if start:
            args.append(start)
        self._git(*args)

    def delete_branch(self, name: str, force: bool = True) -> None:
        self._git("branch", "-D" if force else "-d", name)

    def add(self, *files: str) -> None:
        self._git("add", "--", *files)

    def commit(self, message: str) -> str:
        return self._git("commit", "-m", message)

    def amend_last_commit(self) -> str:
        return self._git("commit", "--amend", "--no-edit")

    def push(self, remote: str, refspec: str, force: bool = False) -> None:
        args = ["push"]
        if force:
            args.append("--force")
        args.extend([remote, refspec])
        self._git(*args)

    def deleted_files_in_history(self) -> dict[str, str]:
        out = self._run(
            "log",
            "--diff-filter=D",
            "--pretty=format:%H",
            "--name-only",
            check=False,
        ).stdout
        deletions: dict[str, str] = {}
        current_sha: Optional[str] = None
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            if len(line) == 40 and " " not in line:
                current_sha = line
            elif current_sha and line not in deletions:
                deletions[line] = current_sha
        return deletions

    def files_added_in_last(self, n: int) -> list[Path]:
        out = self._run(
            "log",
            "-n",
            str(n),
            "--pretty=format:",
            "--name-status",
            "--diff-filter=A",
            check=False,
        ).stdout
        added: list[Path] = []
        for line in out.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                p = self.repo / parts[1]
                if p.is_symlink():
                    continue
                added.append(p)
        return added


def _cutoff(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _parse_commit_ts(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _pending_deletions_matching_history(be: MaintenanceGit) -> list[str]:
    historical = set(be.deleted_files_in_history().keys())
    if not historical:
        return []
    pending: list[str] = []
    for line in be.status_porcelain():
        if len(line) < 4:
            continue
        code, path = line[:2], line[3:].strip()
        if "D" in code and path in historical:
            pending.append(path)
    return pending


def _parse_github_url(url: str) -> Optional[tuple[str, str]]:
    patterns = [
        r"https://(?:[^@/]+@)?github\.com/([^/]+)/([^/]+?)(?:\.git)?$",
        r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$",
    ]
    for pattern in patterns:
        match = re.match(pattern, url)
        if match:
            return match.group(1), match.group(2)
    return None


def _build_token_url(url: str, username: str, token: str, fmt: str) -> str:
    if "@github.com" in url and "github.com" in url and "https://" in url:
        return url
    auth = f"oauth2:{token}" if fmt == "oauth2" else f"{username}:{token}"
    if url.startswith("https://github.com/"):
        return url.replace("https://github.com/", f"https://{auth}@github.com/")
    if url.startswith("git@github.com:"):
        base = url.replace("git@github.com:", "https://github.com/")
        return base.replace("https://github.com/", f"https://{auth}@github.com/")
    return url


def _sanitize_repo_name(name: str) -> str:
    return re.sub(r"[^\w\-\.]", "-", name).lower()


def _token_names(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _get_token(names: Sequence[str]) -> Optional[str]:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        path = Path.home() / ".env"
        if path.exists():
            load_dotenv(path)
    except Exception:
        pass


def _human_size(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    if n < 1024**2:
        return f"{n / 1024:.1f}KB"
    if n < 1024**3:
        return f"{n / 1024**2:.1f}MB"
    return f"{n / 1024**3:.2f}GB"


def _is_valid_slug(slug: str) -> bool:
    parts = slug.split("/")
    return len(parts) == 2 and all(parts)


def _load_repo_list(file_path: Path) -> list[str]:
    if not file_path.exists():
        err(f"Error: {file_path} does not exist")
        raise typer.Exit(1)
    with file_path.open() as f:
        repos = [line.strip() for line in f if line.strip()]
    if not repos:
        err(f"Error: No repositories found in {file_path}")
        raise typer.Exit(1)
    return repos


def _check_gh_cli_installed() -> bool:
    return run_cli(["gh", "--version"]).returncode == 0


def _check_gh_authenticated() -> bool:
    return run_cli(["gh", "auth", "status"]).returncode == 0


def _render_table(title: str, columns: list[str], rows: list[list[str]]) -> None:
    table = Table(title=title)
    for col in columns:
        table.add_column(col)
    for row in rows:
        table.add_row(*row)
    console.print(table)


@app.command("create")
def cmd_create(
    repo_name: str = typer.Argument(..., help="Name of the new repository."),
    description: str = typer.Argument(DEFAULT_DESCRIPTION, help="Repository description."),
    private: bool = typer.Option(False, "--private", help="Make repo private."),
    backend: str = typer.Option("subprocess", "--backend", "-b", help="Backend."),
    env_file: Path = typer.Option(DEFAULT_ENV_FILE, "--env-file", help="Env file."),
    github_username: str = typer.Option(DEFAULT_GITHUB_USERNAME, "--github-username", help="GitHub username."),
) -> None:
    be = resolve_backend(backend, env_file, github_username)
    data = be.github.create_repo(
        name=repo_name,
        description=description,
        private=private,
        auto_init=True,
        owner=github_username,
    )
    if data is None:
        raise typer.Exit(1)
    ok("Repository created successfully!")
    console.print(f"[bold]Name:[/bold] {data.get('name', repo_name)}")
    console.print(f"[bold]URL:[/bold] {data.get('html_url', f'https://github.com/{github_username}/{repo_name}')}")
    console.print(f"[bold]Clone:[/bold] {data.get('clone_url', data.get('ssh_url', ''))}")


@app.command("create-push")
def cmd_create_push(
    name: Optional[str] = typer.Option(None, "-n", "--name"),
    branch: str = typer.Option(DEFAULT_BRANCH, "--branch"),
    commit_message: str = typer.Option(DEFAULT_API_PUSH_COMMIT_MESSAGE, "--commit-message"),
    backend: str = typer.Option("subprocess", "--backend", "-b"),
    env_file: Path = typer.Option(DEFAULT_ENV_FILE, "--env-file"),
    github_username: str = typer.Option(DEFAULT_GITHUB_USERNAME, "--github-username"),
) -> None:
    be = resolve_backend(backend, env_file, github_username)
    cwd = Path.cwd()
    repo_name = name or cwd.name
    if not be.git.is_git_repo(cwd):
        info("No git repository found. Creating new one...")
        be.git.init_repo(cwd)
        ok("Git repository initialized.")
    else:
        info("Existing git repository found.")
    if be.git.is_dirty(cwd):
        be.git.add_all(cwd)
        be.git.commit(cwd, commit_message)
        ok("Changes committed.")
    else:
        info("No changes to commit.")
    if be.git.get_remote_url(cwd) is None:
        info("No remote 'origin' found. Creating GitHub repository...")
        data = be.github.create_repo(name=repo_name, private=False, auto_init=False, owner=github_username)
        if data is None:
            raise typer.Exit(1)
        ssh_url = data.get("ssh_url") or f"git@github.com:{github_username}/{repo_name}.git"
        be.git.add_remote(cwd, "origin", ssh_url)
        ok(f"Remote 'origin' created: {ssh_url}")
    else:
        info(f"Remote 'origin' already exists: {be.git.get_remote_url(cwd)}")
    try:
        be.git.push(cwd, "origin", branch, set_upstream=True)
        ok(f"Successfully pushed to origin/{branch}")
    except Exception as exc:
        err(f"Push failed: {exc}")
        raise typer.Exit(1)


@app.command("gh-create")
def cmd_gh_create(
    name: Optional[str] = typer.Option(None, "-n", "--name"),
    global_gitignore: Path = typer.Option(DEFAULT_GLOBAL_GITIGNORE, "--global-gitignore"),
    commit_message: str = typer.Option(DEFAULT_GH_CREATE_COMMIT_MESSAGE, "--commit-message"),
    backend: str = typer.Option("subprocess", "--backend", "-b"),
    env_file: Path = typer.Option(DEFAULT_ENV_FILE, "--env-file"),
    github_username: str = typer.Option(DEFAULT_GITHUB_USERNAME, "--github-username"),
) -> None:
    be = resolve_backend(backend, env_file, github_username)
    cwd = Path.cwd()
    repo_name = name or cwd.name
    local_gitignore = cwd / ".gitignore"
    if global_gitignore.exists() and not local_gitignore.exists():
        shutil.copy2(global_gitignore, local_gitignore)
        ok(f"Copied {global_gitignore} -> {local_gitignore}")
    elif local_gitignore.exists():
        info(".gitignore already exists in current directory.")
    else:
        warn(f"No global .gitignore found at {global_gitignore}")
    if be.git.is_git_repo(cwd):
        info("Git repository already initialized.")
    else:
        info("Initializing git repository...")
        be.git.init_repo(cwd)
    if be.git.get_remote_url(cwd) is not None:
        info("Remote 'origin' already exists.")
        return
    if be.github.repo_exists(github_username, repo_name):
        info(f"GitHub repo '{repo_name}' already exists on your account.")
        ssh_url = f"git@github.com:{github_username}/{repo_name}.git"
        be.git.add_remote(cwd, "origin", ssh_url)
        ok(f"Added remote origin: {ssh_url}")
    else:
        info(f"GitHub repo '{repo_name}' does not exist yet.")
        data = be.github.create_repo(name=repo_name, private=False, auto_init=False, owner=github_username)
        if data is None:
            raise typer.Exit(1)
        ssh_url = data.get("ssh_url") or f"git@github.com:{github_username}/{repo_name}.git"
        be.git.add_remote(cwd, "origin", ssh_url)
        ok(f"Added remote origin: {ssh_url}")
    be.git.add_all(cwd)
    if be.git.commit(cwd, commit_message):
        ok("Committing changes...")
    else:
        info("No changes to commit.")
    branch = be.git.current_branch(cwd)
    info(f"Pushing branch '{branch}'...")
    try:
        be.git.push(cwd, "origin", branch, set_upstream=True)
    except Exception as exc:
        err(f"Push failed: {exc}")
        raise typer.Exit(1)
    ok(f"Success! Repository '{repo_name}' is on GitHub.")
    console.print(f"[bold]View at:[/bold] https://github.com/{github_username}/{repo_name}")


@app.command("gh-cli")
def cmd_gh_cli(
    name: Optional[str] = typer.Option(None, "-n", "--name"),
    branch: str = typer.Option(DEFAULT_BRANCH, "--branch"),
    commit_message: str = typer.Option(DEFAULT_GH_CLI_COMMIT_MESSAGE, "--commit-message"),
    backend: str = typer.Option("subprocess", "--backend", "-b"),
    env_file: Path = typer.Option(DEFAULT_ENV_FILE, "--env-file"),
    github_username: str = typer.Option(DEFAULT_GITHUB_USERNAME, "--github-username"),
) -> None:
    be = resolve_backend(backend, env_file, github_username)
    cwd = Path.cwd()
    repo_name = name or cwd.name
    info(f"Repository name: {repo_name}")
    if not be.git.is_git_repo(cwd):
        info("Initializing git repository...")
        be.git.init_repo(cwd)
    else:
        info("Git repository already initialized.")
    origin_url = be.git.get_remote_url(cwd)
    if origin_url is None:
        info(f"Creating GitHub repository '{repo_name}'...")
        data = be.github.create_repo(name=repo_name, private=False, auto_init=False, owner=github_username)
        if data is None:
            raise typer.Exit(1)
    else:
        info("Remote 'origin' already exists. Checking if repo exists on GitHub...")
        fetch = run_cli(["git", "fetch", "origin"], cwd=cwd)
        if fetch.returncode == 0:
            info("GitHub repository exists. Will push changes.")
        else:
            warn("Remote exists but seems inaccessible. You might need to authenticate.")
            console.print(f"[bold]Remote URL:[/bold] {origin_url}")
    info("Adding all files...")
    be.git.add_all(cwd)
    if be.git.is_dirty(cwd):
        info("Committing changes...")
        if not be.git.commit(cwd, commit_message):
            info("Nothing to commit after staging.")
    else:
        info("No changes to commit.")
    info("Pushing to GitHub...")
    push_branch = be.git.current_branch(cwd) or branch
    try:
        be.git.push(cwd, "origin", push_branch, set_upstream=True)
    except Exception as exc:
        err(f"Push failed: {exc}")
        raise typer.Exit(1)
    ok(f"Success! Repository '{repo_name}' is now on GitHub.")
    console.print(f"[bold]View at:[/bold] https://github.com/{github_username}/{repo_name}")


@app.command("managed")
def cmd_managed(
    name: Optional[str] = typer.Option(None, "-n", "--name"),
    message: Optional[str] = typer.Option(None, "-m", "--message"),
    git_email: str = typer.Option(DEFAULT_GIT_EMAIL, "--git-email"),
    git_user: str = typer.Option(DEFAULT_GIT_USER, "--git-user"),
    branch: str = typer.Option(DEFAULT_BRANCH, "--branch"),
    backend: str = typer.Option("subprocess", "--backend", "-b"),
    env_file: Path = typer.Option(DEFAULT_ENV_FILE, "--env-file"),
    github_username: str = typer.Option(DEFAULT_GITHUB_USERNAME, "--github-username"),
) -> None:
    try:
        be = resolve_backend(backend, env_file, github_username)
        cwd = Path.cwd()
        repo_name = name or cwd.name
        repo_url = f"https://github.com/{github_username}/{repo_name}.git"
        console.rule(f"GitHub Repository Manager (backend: {be.name})")
        console.print(f"Directory: {cwd}")
        console.print(f"Repository: {repo_name}")
        console.print(f"GitHub User: {github_username}")
        console.print(f"Email: {git_email}")
        console.rule()
        if backend == "subprocess":
            if not _check_gh_cli_installed():
                err("GitHub CLI (gh) is not installed.")
                raise typer.Exit(1)
            if not _check_gh_authenticated():
                err("GitHub CLI is not authenticated.")
                raise typer.Exit(1)
            ok("GitHub CLI is installed and authenticated")
        if be.git.is_git_repo(cwd):
            warn(f"Git repository already exists in {cwd}")
            current = be.git.get_remote_url(cwd)
            console.print(f"Current remote: {current or 'None'}")
            while True:
                console.print("[bold]Options:[/bold]")
                console.print("1. Merge changes (stage and commit to current repo)")
                console.print("2. Create new repository (enter new name)")
                console.print("3. Exit")
                choice = typer.prompt("Select option (1-3)").strip()
                if choice == "1":
                    ok("Using existing repository")
                    break
                if choice == "2":
                    new_name = typer.prompt("Enter new repository name").strip()
                    if not new_name:
                        err("Repository name cannot be empty.")
                        continue
                    repo_name = new_name
                    repo_url = f"https://github.com/{github_username}/{repo_name}.git"
                    be.git.remove_remote(cwd, "origin")
                    break
                if choice == "3":
                    info("Exiting...")
                    raise typer.Exit(0)
                err("Invalid choice.")
        else:
            info(f"Initializing local git repository in {cwd}...")
            be.git.init_repo(cwd)
            be.git.config_user(cwd, git_user, git_email)
            ok("Local repository initialized")
        visible = [f for f in cwd.glob("*") if f.name != ".git"]
        hidden = [f for f in cwd.glob(".*") if f.name not in {".git", ".", ".."}]
        if not (visible or hidden):
            readme = cwd / "README.md"
            if not readme.exists():
                readme.write_text(f"# {repo_name}\nRepository initialized on {datetime.now():%Y-%m-%d %H:%M:%S}\n")
                ok("Created README.md")
        info("Staging all changes...")
        be.git.add_all(cwd)
        ok("Changes staged")
        msg = message or datetime.now().strftime("Auto-commit: %Y-%m-%d %H:%M:%S")
        info(f"Committing changes with message: '{msg}'")
        if not be.git.commit(cwd, msg):
            warn("Could not commit changes.")
            raise typer.Exit(1)
        current = be.git.current_branch(cwd)
        if current and current != branch:
            info(f"Renaming branch from '{current}' to '{branch}'...")
            be.git.rename_branch(cwd, branch)
        if not be.github.repo_exists(github_username, repo_name):
            info(f"Creating repository on GitHub: {repo_name}...")
            data = be.github.create_repo(name=repo_name, private=False, auto_init=False, owner=github_username)
            if data is None:
                err("Failed to create repository on GitHub")
                raise typer.Exit(1)
            ok("Repository created on GitHub")
        else:
            ok(f"Repository {repo_name} already exists on GitHub")
        info(f"Adding remote: {repo_url}")
        current_remote = be.git.get_remote_url(cwd)
        if current_remote:
            if current_remote != repo_url:
                be.git.set_remote_url(cwd, "origin", repo_url)
                ok("Remote URL updated")
        else:
            be.git.add_remote(cwd, "origin", repo_url)
            ok("Remote added")
        info(f"Pushing to GitHub ({branch} branch)...")
        try:
            be.git.push(cwd, "origin", branch, set_upstream=True)
            ok("Successfully pushed to GitHub")
        except Exception as exc:
            err(f"Push failed: {exc}")
            raise typer.Exit(1)
        console.rule()
        ok("Success! Repository created and pushed to GitHub")
        console.print(f"[bold]Repository URL:[/bold] https://github.com/{github_username}/{repo_name}")
    except KeyboardInterrupt:
        info("Exiting...")
        raise typer.Exit(0)
    except typer.Exit:
        raise
    except Exception as exc:
        err(f"Unexpected error: {exc}")
        traceback.print_exc()
        raise typer.Exit(1)


@app.command("checkout-previous")
def cmd_checkout_previous(
    repo: Path = typer.Option(Path("."), "-C", "--repo"),
    prefix: str = typer.Option("2026-08-29", "--prefix"),
    yes: bool = typer.Option(False, "-y", "--yes"),
    backend: str = typer.Option("subprocess", "--backend", "-b"),
) -> None:
    root = Path(repo).resolve()
    if not root.is_dir():
        err(f"Not a directory: {root}")
        raise typer.Exit(1)
    candidates = [root] + [p for p in root.iterdir() if p.is_dir() and not p.is_symlink()]
    found = False
    for candidate in candidates:
        be = MaintenanceGit(candidate, backend)
        if not be.is_repo():
            continue
        found = True
        try:
            head_list = be.log(ref="HEAD", n=1)
        except Exception as e:
            err(f"{candidate.name}: {e}")
            continue
        if not head_list:
            continue
        head = head_list[0]
        if not head.subject.startswith(prefix):
            info(f"[skip] {candidate.name}: latest commit does not start with {prefix!r}")
            continue
        if not head.parents:
            info(f"[skip] {candidate.name}: no parent commit")
            continue
        target = head.parents[0]
        console.print(f"[bold][match][/bold] Repository: {candidate.name}")
        console.print(f"        Path: {candidate}")
        console.print(f"        Current commit: {head.short}")
        console.print(f"        Latest message: {head.subject}")
        console.print(f"        Target commit: {target[:8]}")
        if not yes:
            ans = typer.prompt(f"Checkout {target[:8]} in {candidate.name}? [y/N]", default="N").strip().lower()
            if ans not in ("y", "yes"):
                info(f"[skip] {candidate.name}: cancelled")
                continue
        be.checkout(target)
        ok(f"[done] {candidate.name}: now at {target[:8]}")
    if not found:
        info("No git repositories found.")


@app.command("rm-commits")
def cmd_rm_commits(
    repo: Path = typer.Option(Path("."), "-C", "--repo"),
    days: int = typer.Option(30, "--days"),
    yes: bool = typer.Option(False, "-y", "--yes"),
    backend: str = typer.Option("subprocess", "--backend", "-b"),
) -> None:
    rp = Path(repo).resolve()
    be = MaintenanceGit(rp, backend)
    if not be.is_repo():
        err(f"{rp} is not a git repository")
        raise typer.Exit(1)
    branch = be.current_branch()
    if branch is None:
        err("HEAD is detached — checkout a branch first")
        raise typer.Exit(1)
    info(f"Current branch: {branch}")
    cutoff = _cutoff(days)
    info(f"Cutoff: {cutoff:%Y-%m-%d %H:%M:%S UTC}")
    if be.is_dirty(untracked=True):
        err("Working directory is not clean — commit or stash first")
        raise typer.Exit(1)
    commits = be.log(ref=branch)
    if not commits:
        info("No commits found.")
        return
    keep = [c for c in commits if _parse_commit_ts(c.timestamp) > cutoff]
    old = [c for c in commits if _parse_commit_ts(c.timestamp) <= cutoff]
    if not old:
        info(f"No commits older than {days} days.")
        return
    if not keep:
        err("All commits would be deleted — aborting")
        raise typer.Exit(1)
    info(f"Found {len(old)} commit(s) to delete (older than {days} days)")
    info(f"Keeping {len(keep)} commit(s)")
    for c in old[-5:]:
        console.print(f"  {c.short} - {c.date:%Y-%m-%d %H:%M} - {c.subject}")
    new_head = keep[0]
    info(f"New HEAD will be: {new_head.short} - {new_head.subject}")
    if not yes:
        ans = (
            typer.prompt("This will PERMANENTLY DELETE those commits. Continue? (yes/no)", default="no").strip().lower()
        )
        if ans != "yes":
            info("Cancelled.")
            return
    backup = f"backup-{branch}-{datetime.now():%Y%m%d%H%M%S}"
    info(f"Creating backup branch: {backup}")
    be.create_branch(backup)
    be.reset(new_head.sha, "hard")
    ok(f"Deleted {len(old)} commit(s)")
    console.print(f"Backup branch: {backup}")
    console.print(f"To restore: git reset --hard {backup}")


@app.command("cut")
def cmd_cut(
    repo: Path = typer.Option(Path("."), "-C", "--repo"),
    days: int = typer.Option(30, "--days"),
    method: str = typer.Option("squash", "--method"),
    yes: bool = typer.Option(False, "-y", "--yes"),
    backend: str = typer.Option("subprocess", "--backend", "-b"),
) -> None:
    rp = Path(repo).resolve()
    be = MaintenanceGit(rp, backend)
    if not be.is_repo():
        err(f"{rp} is not a git repository")
        raise typer.Exit(1)
    cutoff = _cutoff(days)
    info(f"Cutoff date: {cutoff:%Y-%m-%d %H:%M:%S UTC}")
    commits = be.log(ref="HEAD")
    if not commits:
        info("No commits found.")
        return
    keep = [c for c in commits if _parse_commit_ts(c.timestamp) > cutoff]
    old = [c for c in commits if _parse_commit_ts(c.timestamp) <= cutoff]
    info(f"Commits to keep:   {len(keep)}")
    info(f"Commits to remove: {len(old)}")
    if not keep:
        err("No commits to keep — aborting")
        raise typer.Exit(1)
    if not old:
        info("No old commits to remove.")
        return
    oldest_kept = keep[-1]
    console.print(f"Oldest kept: {oldest_kept.short} - {oldest_kept.subject}")
    console.print(f"Date:        {oldest_kept.date}")
    if not yes:
        ans = typer.prompt("Rewrite history? (yes/no)", default="no").strip().lower()
        if ans != "yes":
            info("Cancelled.")
            return
    branch = be.current_branch()
    if method == "squash":
        be.reset(oldest_kept.sha, "hard")
        ok(f"Old commits removed (reset --hard to {oldest_kept.short}).")
        if branch:
            console.print(f"Force push needed: git push --force origin {branch}")
        return
    if branch is None:
        err("Cannot use orphan method on a detached HEAD")
        raise typer.Exit(1)
    new_branch = f"cleaned_{branch}"
    info(f"Creating orphan branch {new_branch}...")
    subprocess.run(["git", "checkout", "--orphan", new_branch], cwd=str(rp), check=True)
    for c in reversed(keep):
        try:
            be.cherry_pick(c.sha, allow_empty=True)
        except subprocess.CalledProcessError as e:
            warn(f"cherry-pick {c.short} failed: {e}")
    ok(f"New branch {new_branch} with {len(keep)} commit(s) created.")
    console.print(
        f"To replace the original: git checkout {branch} && git reset --hard {new_branch} && git branch -D {new_branch}"
    )


@app.command("del-remote-commits")
def cmd_del_remote_commits(
    repo: Path = typer.Option(Path("."), "-C", "--repo"),
    branch: str = typer.Option("master", "--branch"),
    days: int = typer.Option(7, "--days"),
    no_push: bool = typer.Option(False, "--no-push"),
    yes: bool = typer.Option(False, "-y", "--yes"),
    backend: str = typer.Option("subprocess", "--backend", "-b"),
) -> None:
    rp = Path(repo).resolve()
    be = MaintenanceGit(rp, backend)
    if not be.is_repo():
        err(f"{rp} is not a git repository")
        raise typer.Exit(1)
    try:
        refs = subprocess.run(
            ["git", "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"],
            cwd=str(rp),
            capture_output=True,
            text=True,
        ).stdout
        if branch == "master" and "origin/main" in refs and "origin/master" not in refs:
            branch = "main"
    except Exception:
        pass
    cutoff = _cutoff(days)
    commits = be.log(ref=branch)
    if not commits:
        err(f"No commits on {branch}")
        raise typer.Exit(1)
    keep = [c for c in commits if _parse_commit_ts(c.timestamp) >= cutoff]
    if not keep:
        err(f"No commits within {days} days — nothing to keep, aborting")
        raise typer.Exit(1)
    new_head = keep[0]
    info(f"Branch: {branch}")
    info(f"Cutoff: {cutoff:%Y-%m-%d %H:%M:%S UTC}")
    info(f"Resetting to: {new_head.short} - {new_head.subject}")
    if not yes:
        ans = typer.prompt("Proceed with local reset and force-push? (yes/no)", default="no").strip().lower()
        if ans != "yes":
            info("Cancelled.")
            return
    if be.current_branch() != branch:
        be.checkout(branch)
    be.reset(new_head.sha, "hard")
    ok(f"Local branch {branch} reset to {new_head.short}")
    if no_push:
        info("Skipping push (--no-push).")
    else:
        try:
            be.push("origin", f"{branch}:{branch}", force=True)
            ok(f"Force-pushed {branch} to origin")
        except Exception as e:
            err(f"push failed: {e}")
            raise typer.Exit(1)


@app.command("list-added")
def cmd_list_added(
    repo: Path = typer.Option(Path("."), "-C", "--repo"),
    n: int = typer.Option(10, "-n"),
    backend: str = typer.Option("subprocess", "--backend", "-b"),
) -> None:
    rp = Path(repo).resolve()
    be = MaintenanceGit(rp, backend)
    if not be.is_repo():
        err(f"{rp} is not a git repository")
        raise typer.Exit(1)
    added = be.files_added_in_last(n)
    if not added:
        info(f"No files created in the last {n} commit(s).")
        return
    for path in added:
        try:
            console.print(str(path.relative_to(rp)))
        except ValueError:
            console.print(str(path))


@app.command("restore-deleted")
def cmd_restore_deleted(
    repo: Path = typer.Option(Path("."), "-C", "--repo"),
    message: str = typer.Option("removed files", "-m", "--message"),
    backend: str = typer.Option("subprocess", "--backend", "-b"),
) -> None:
    rp = Path(repo).resolve()
    be = MaintenanceGit(rp, backend)
    if not be.is_repo():
        err(f"{rp} is not a git repository")
        raise typer.Exit(1)
    info("Analyzing repository history for file deletions...")
    deletions = be.deleted_files_in_history()
    if not deletions:
        ok("No deleted files found in this repository's history.")
        return
    missing = [(p, sha) for p, sha in deletions.items() if not (rp / p).exists()]
    if not missing:
        info("All historically deleted files are already present.")
        return
    warn(f"Found {len(missing)} missing file(s).")
    restored = 0
    for p, sha in missing:
        info(f"Restoring: {p} (from commit prior to {sha[:8]})")
        try:
            subprocess.run(["git", "checkout", f"{sha}^", "--", p], cwd=str(rp), check=True, capture_output=True)
            subprocess.run(["git", "add", "--", p], cwd=str(rp), check=True, capture_output=True)
            restored += 1
        except subprocess.CalledProcessError:
            try:
                subprocess.run(["git", "checkout", sha, "--", p], cwd=str(rp), check=True, capture_output=True)
                subprocess.run(["git", "add", "--", p], cwd=str(rp), check=True, capture_output=True)
                restored += 1
            except subprocess.CalledProcessError as e2:
                err(f"   could not restore {p}: {e2}")
    if restored:
        info(f"Committing {restored} restored file(s)...")
        try:
            be.commit(message)
            ok("Commit created.")
        except Exception as e:
            err(f"commit failed: {e}")
            raise typer.Exit(1)
    else:
        err("No files were successfully restored.")


@app.command("stage-deleted")
def cmd_stage_deleted(
    repo: Path = typer.Option(Path("."), "-C", "--repo"),
    message: str = typer.Option("removed files", "-m", "--message"),
    backend: str = typer.Option("subprocess", "--backend", "-b"),
) -> None:
    rp = Path(repo).resolve()
    be = MaintenanceGit(rp, backend)
    if not be.is_repo():
        err(f"{rp} is not a git repository")
        raise typer.Exit(1)
    pending = _pending_deletions_matching_history(be)
    if not pending:
        ok("No pending historical file deletions need staging.")
        return
    warn(f"Found {len(pending)} deleted file(s) to stage:")
    for p in pending:
        console.print(f"  {p}")
    info("Staging...")
    for p in pending:
        be.add(p)
    info(f'Committing: "{message}"')
    try:
        be.commit(message)
        ok("Commit created.")
    except Exception as e:
        err(f"commit failed: {e}")
        raise typer.Exit(1)


@app.command("squash-deletions")
def cmd_squash_deletions(
    repo: Path = typer.Option(Path("."), "-C", "--repo"),
    backend: str = typer.Option("subprocess", "--backend", "-b"),
) -> None:
    rp = Path(repo).resolve()
    be = MaintenanceGit(rp, backend)
    if not be.is_repo():
        err(f"{rp} is not a git repository")
        raise typer.Exit(1)
    pending = _pending_deletions_matching_history(be)
    if not pending:
        ok("No pending historical file deletions to squash.")
        return
    warn(f"Found {len(pending)} deleted file(s) to squash:")
    for p in pending:
        console.print(f"  {p}")
    info("Staging...")
    for p in pending:
        be.add(p)
    info("Amending last commit (--amend --no-edit)...")
    try:
        be.amend_last_commit()
        ok("Last commit amended.")
    except Exception as e:
        err(f"amend failed: {e}")
        raise typer.Exit(1)


@app.command("age-filter")
def cmd_age_filter(
    mode: str = typer.Argument(..., help="clean or smudge"),
    age_bin: Optional[str] = typer.Option(None, "--age-bin"),
    public_key: Path = typer.Option(Path.home() / ".config" / "age" / "public.key", "--public-key"),
    private_key: Path = typer.Option(Path.home() / ".config" / "age" / "keys.txt", "--private-key"),
) -> None:
    if mode not in ("clean", "smudge"):
        err("mode must be 'clean' or 'smudge'")
        raise typer.Exit(1)
    resolved = age_bin
    if not resolved:
        default = Path.home() / ".." / "usr" / "bin" / "age"
        resolved = str(default) if default.exists() else "age"
    if mode == "clean":
        pub_path = Path(public_key).expanduser()
        if not pub_path.exists():
            err(f"missing public key file: {pub_path}")
            raise typer.Exit(1)
        recipient = pub_path.read_text(encoding="utf-8").strip()
        if not recipient:
            err("public key file is empty")
            raise typer.Exit(1)
        data = sys.stdin.buffer.read()
        r = subprocess.run([resolved, "-r", recipient, "-a"], input=data, capture_output=True)
        if r.returncode != 0:
            err(f"age encrypt failed: {r.stderr.decode(errors='replace')}")
            raise typer.Exit(1)
        sys.stdout.buffer.write(r.stdout)
        return
    data = sys.stdin.buffer.read()
    if not data.lstrip().startswith(b"-----BEGIN AGE ENCRYPTED FILE-----"):
        sys.stdout.buffer.write(data)
        return
    priv = Path(private_key).expanduser()
    if not priv.exists():
        warn("no private key; leaving ciphertext")
        sys.stdout.buffer.write(data)
        return
    r = subprocess.run([resolved, "-d", "-i", str(priv)], input=data, capture_output=True)
    if r.returncode != 0:
        err(f"age decrypt failed: {r.stderr.decode(errors='replace')}")
        raise typer.Exit(1)
    sys.stdout.buffer.write(r.stdout)


def _open_repo(path: Path, search_parent: bool, init_if_missing: bool) -> Any:
    from git import InvalidGitRepositoryError, Repo

    try:
        return Repo(path, search_parent_directories=search_parent)
    except InvalidGitRepositoryError:
        if init_if_missing:
            repo = Repo.init(path)
            ok("Repository initialized.")
            return repo
        err("Not a git repository.")
        raise typer.Exit(1)


def _ensure_gitignore(repo: Any, mode: str, source: Path, dest: Path) -> None:
    if mode == "none":
        return
    root = Path(repo.working_tree_dir or ".")
    dest_path = dest if dest.is_absolute() else root / dest
    if dest_path.exists():
        info(f"{dest_path} already exists.")
        return
    source_path = source.expanduser()
    if not source_path.exists():
        warn(f"{source_path} does not exist. Skipping.")
        return
    if mode == "copy":
        shutil.copy(source_path, dest_path)
        ok(f"Copied {source_path} -> {dest_path}")
    elif mode == "symlink":
        dest_path.symlink_to(source_path)
        ok(f"Symlinked {source_path} -> {dest_path}")


def _find_python_files(root: Path) -> list[Path]:
    files: set[Path] = set()
    for path in root.rglob("*.py"):
        if path.is_file():
            files.add(path)
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix:
            continue
        try:
            first = path.open(encoding="utf-8", errors="ignore").readline().strip()
        except OSError:
            continue
        if first.startswith("#!") and "python" in first.lower():
            files.add(path)
    return sorted(files)


def _run_cmd(cmd: Sequence[str]) -> bool:
    try:
        subprocess.check_call(cmd)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        err(f"Command failed: {' '.join(cmd)}: {exc}")
        return False


def _format_black(repo: Any, black_cmd: str) -> bool:
    root = Path(repo.working_tree_dir or ".")
    files = _find_python_files(root)
    if not files:
        info("No Python files found.")
        return True
    info("Formatting Python files with black:")
    for path in files:
        info(f"-> {path}")
        if not _run_cmd([black_cmd, str(path)]):
            return False
    return True


def _stage_and_commit(repo: Any, message: str, add_mode: str) -> Optional[str]:
    from git import GitCommandError

    if add_mode == "all":
        repo.git.add("--all")
    else:
        repo.index.add("*")
    try:
        repo.git.commit("-m", message)
        commit = repo.head.commit
        ok(f'Committed with message: "{message}"')
        info(f"Commit hash: {commit.hexsha[:7]}")
        return commit.hexsha
    except GitCommandError as exc:
        text = str(exc).lower()
        if "nothing to commit" in text or "no changes" in text:
            info("No changes to commit.")
            return None
        err(f"Commit failed: {exc}")
        raise typer.Exit(1)


def _github_login(token: str, override: Optional[str]) -> str:
    if override:
        return override
    from github import Github

    return Github(token).get_user().login


def _create_repo_via_pygithub(
    token: str,
    name: str,
    description: Optional[str],
    private: bool,
    auto_init: bool,
    reuse_existing: bool,
) -> str:
    from github import Github, GithubException

    gh = Github(token)
    user = gh.get_user()
    if reuse_existing:
        try:
            repo = user.get_repo(name)
            info(f"Remote repository '{name}' already exists.")
            return repo.clone_url
        except GithubException:
            pass
    info(f"Creating remote repository '{name}'...")
    repo = user.create_repo(name=name, description=description, private=private, auto_init=auto_init)
    return repo.clone_url


def _fork_repo(token: str, owner: str, name: str) -> str:
    from github import Github, GithubException

    gh = Github(token)
    user = gh.get_user()
    try:
        fork = user.get_repo(name)
        info(f"Fork already exists: {fork.full_name}")
        return fork.clone_url
    except GithubException:
        upstream = gh.get_repo(f"{owner}/{name}")
        info(f"Forking {owner}/{name}...")
        fork = user.create_fork(upstream)
        info(f"Created fork: {fork.full_name}")
        return fork.clone_url


def _push_remote(
    repo: Any,
    remote_name: str,
    branch: str,
    token_auth: str,
    token: Optional[str],
    github_user: Optional[str],
    token_url_format: str,
    set_upstream: bool,
) -> None:
    from git import GitCommandError

    try:
        remote = repo.remote(remote_name)
    except ValueError:
        err(f"Remote '{remote_name}' not configured. Skipping push.")
        return
    original_url = remote.url
    auth_applied = False
    if token_auth in ("temporary", "persistent") and token and github_user:
        new_url = _build_token_url(original_url, github_user, token, token_url_format)
        if new_url != original_url:
            remote.set_url(new_url)
            auth_applied = True
    try:
        if set_upstream:
            repo.git.push("--set-upstream", remote_name, branch)
        else:
            remote.push(refspec=f"{branch}:{branch}")
        ok(f"Successfully pushed to {remote_name}/{branch}")
    except GitCommandError as exc:
        text = str(exc)
        err(f"Push failed: {exc}")
        if "403" in text or "401" in text:
            err("Authentication failed. Check your GitHub token.")
        raise typer.Exit(1)
    finally:
        if auth_applied and token_auth == "temporary":
            remote.set_url(original_url)


def _cli_git_clone(owner: str, repo: str, destination: Path) -> bool:
    url = f"https://github.com/{owner}/{repo}.git"
    info(f"Cloning {owner}/{repo} (shallow clone)...")
    try:
        subprocess.run(["git", "clone", url, str(destination)], check=True)
        ok(f"Successfully cloned into: {destination}")
        return True
    except FileNotFoundError:
        err("git command not found.")
        return False
    except Exception as exc:
        err(f"An unexpected error occurred during cloning: {exc}")
        return False


def _gh_size_mb(owner: str, repo: str, token: Optional[str] = None) -> Optional[float]:
    import requests

    url = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        size = data.get("size")
        if size is None:
            return None
        return round(size / 1024.0, 2)
    except Exception as exc:
        err(f"API error for {owner}/{repo}: {exc}")
    return None


@app.command("commit")
def cmd_commit(
    repo: Path = typer.Option(Path("."), "--repo"),
    search_parent: bool = typer.Option(True, "--search-parent/--no-search-parent"),
    init_if_missing: bool = typer.Option(False, "--init-if-missing"),
    message: Optional[str] = typer.Option(None, "--message"),
    message_prefix: str = typer.Option("", "--message-prefix"),
    add_mode: str = typer.Option("all", "--add-mode"),
    gitignore_mode: str = typer.Option("none", "--gitignore-mode"),
    gitignore_source: Path = typer.Option(Path.home() / ".gitignore", "--gitignore-source"),
    gitignore_dest: Path = typer.Option(Path(".gitignore"), "--gitignore-dest"),
    format_black: bool = typer.Option(False, "--format-black"),
    black_cmd: str = typer.Option("black", "--black-cmd"),
) -> None:
    _load_dotenv()
    r = _open_repo(repo, search_parent, init_if_missing)
    _ensure_gitignore(r, gitignore_mode, gitignore_source, gitignore_dest)
    if format_black and not _format_black(r, black_cmd):
        raise typer.Exit(1)
    msg = message or f"{message_prefix}{datetime.now():%Y-%m-%d %H:%M:%S}"
    _stage_and_commit(r, msg, add_mode)
    info("Done.")


@app.command("push")
def cmd_push(
    repo: Path = typer.Option(Path("."), "--repo"),
    search_parent: bool = typer.Option(True, "--search-parent/--no-search-parent"),
    init_if_missing: bool = typer.Option(False, "--init-if-missing"),
    remote_name: str = typer.Option("origin", "--remote-name"),
    branch: Optional[str] = typer.Option(None, "--branch"),
    message: Optional[str] = typer.Option(None, "--message"),
    message_prefix: str = typer.Option("", "--message-prefix"),
    add_mode: str = typer.Option("all", "--add-mode"),
    gitignore_mode: str = typer.Option("none", "--gitignore-mode"),
    gitignore_source: Path = typer.Option(Path.home() / ".gitignore", "--gitignore-source"),
    gitignore_dest: Path = typer.Option(Path(".gitignore"), "--gitignore-dest"),
    format_black: bool = typer.Option(False, "--format-black"),
    black_cmd: str = typer.Option("black", "--black-cmd"),
    token_env_vars: str = typer.Option("GITHUB_TOKEN,GH_TOKEN,GIT_TOKEN", "--token-env-vars"),
    github_user: Optional[str] = typer.Option(None, "--github-user"),
    create_repo: bool = typer.Option(False, "--create-repo"),
    fork_origin: bool = typer.Option(False, "--fork-origin"),
    push_to_fork: bool = typer.Option(False, "--push-to-fork/--no-push-to-fork"),
    fork_remote_name: str = typer.Option("fork", "--fork-remote-name"),
    private: bool = typer.Option(False, "--private"),
    auto_init: bool = typer.Option(False, "--auto-init/--no-auto-init"),
    description: Optional[str] = typer.Option(None, "--description"),
    reuse_existing_repo: bool = typer.Option(True, "--reuse-existing-repo/--no-reuse-existing-repo"),
    token_auth: str = typer.Option("none", "--token-auth"),
    fork_token_auth: str = typer.Option("persistent", "--fork-token-auth"),
    token_url_format: str = typer.Option("user", "--token-url-format"),
    set_upstream: bool = typer.Option(False, "--set-upstream/--no-set-upstream"),
    push_if_no_changes: bool = typer.Option(True, "--push-if-no-changes/--no-push-if-no-changes"),
    fail_if_no_changes: bool = typer.Option(False, "--fail-if-no-changes"),
    require_remote: bool = typer.Option(False, "--require-remote"),
) -> None:
    from git import Repo

    _load_dotenv()
    names = _token_names(token_env_vars)
    token = _get_token(names)
    if (create_repo or fork_origin or push_to_fork or token_auth != "none") and not token:
        err("GITHUB_TOKEN not found.")
        raise typer.Exit(1)
    r = _open_repo(repo, search_parent, init_if_missing)
    _ensure_gitignore(r, gitignore_mode, gitignore_source, gitignore_dest)
    if format_black and not _format_black(r, black_cmd):
        raise typer.Exit(1)
    try:
        active = branch or r.active_branch.name
    except TypeError:
        err("In detached HEAD state. Skipping push.")
        raise typer.Exit(1)
    msg = message or f"{message_prefix}{datetime.now():%Y-%m-%d %H:%M:%S}"
    commit_hash = _stage_and_commit(r, msg, add_mode)
    if commit_hash is None:
        if fail_if_no_changes:
            err("No changes to commit.")
            raise typer.Exit(1)
        if not push_if_no_changes:
            info("Skipping push because there are no changes.")
            return
    gh_user = github_user
    if token and (create_repo or fork_origin or push_to_fork or token_auth != "none"):
        try:
            gh_user = _github_login(token, gh_user)
        except Exception as exc:
            err(f"Error getting GitHub username: {exc}")
            if create_repo or fork_origin:
                raise typer.Exit(1)
    remote_names = [rm.name for rm in r.remotes]
    changed = False
    if remote_name not in remote_names:
        if create_repo:
            if not token:
                err("GITHUB_TOKEN not found. Cannot create remote repository.")
                raise typer.Exit(1)
            name = _sanitize_repo_name(Path(r.working_tree_dir or ".").name)
            url = _create_repo_via_pygithub(token, name, description, private, auto_init, reuse_existing_repo)
            r.create_remote(remote_name, url)
            ok(f"Added remote '{remote_name}': {url}")
            changed = True
    else:
        if fork_origin and token and gh_user:
            remote = r.remote(remote_name)
            parsed = _parse_github_url(remote.url)
            if parsed:
                owner, name = parsed
                if owner.lower() != gh_user.lower():
                    url = _fork_repo(token, owner, name)
                    remote.set_url(url)
                    info(f"Updated remote '{remote_name}' to fork: {url}")
                    changed = True
    push_remote_name = remote_name
    if push_to_fork and token:
        try:
            origin = r.remote(remote_name)
        except ValueError:
            origin = None
        if origin:
            parsed = _parse_github_url(origin.url)
            if parsed:
                owner, name = parsed
                login = gh_user or _github_login(token, None)
                if owner.lower() != login.lower():
                    login = _github_login(token, gh_user)
                    url = _fork_repo(token, owner, name)
                    if fork_remote_name in [rm.name for rm in r.remotes]:
                        r.remote(fork_remote_name).set_url(url)
                    else:
                        r.create_remote(fork_remote_name, url)
                    push_remote_name = fork_remote_name
    if push_remote_name not in [rm.name for rm in r.remotes]:
        warn(f"Remote '{push_remote_name}' not configured. Changes committed locally only.")
        if require_remote:
            raise typer.Exit(1)
        return
    auth_mode = token_auth if push_remote_name == remote_name else fork_token_auth
    _push_remote(r, push_remote_name, active, auth_mode, token, gh_user, token_url_format, set_upstream or changed)
    ok("All done! Changes are now on GitHub.")


@app.command("sync")
def cmd_sync(
    repo: Path = typer.Option(Path("."), "--repo"),
    search_parent: bool = typer.Option(True, "--search-parent/--no-search-parent"),
    init_if_missing: bool = typer.Option(False, "--init-if-missing"),
    remote_name: str = typer.Option("origin", "--remote-name"),
    branch: Optional[str] = typer.Option(None, "--branch"),
    message: Optional[str] = typer.Option(None, "--message"),
    message_prefix: str = typer.Option("", "--message-prefix"),
    add_mode: str = typer.Option("all", "--add-mode"),
    gitignore_mode: str = typer.Option("none", "--gitignore-mode"),
    gitignore_source: Path = typer.Option(Path.home() / ".gitignore", "--gitignore-source"),
    gitignore_dest: Path = typer.Option(Path(".gitignore"), "--gitignore-dest"),
    token_env_vars: str = typer.Option("GITHUB_TOKEN,GH_TOKEN,GIT_TOKEN", "--token-env-vars"),
    github_user: Optional[str] = typer.Option(None, "--github-user"),
    push_to_fork: bool = typer.Option(True, "--push-to-fork/--no-push-to-fork"),
    fork_remote_name: str = typer.Option("fork", "--fork-remote-name"),
    token_auth: str = typer.Option("none", "--token-auth"),
    fork_token_auth: str = typer.Option("persistent", "--fork-token-auth"),
    token_url_format: str = typer.Option("user", "--token-url-format"),
    set_upstream: bool = typer.Option(False, "--set-upstream/--no-set-upstream"),
    do_commit: bool = typer.Option(False, "--commit"),
    allow_dirty: bool = typer.Option(False, "--allow-dirty"),
) -> None:
    _load_dotenv()
    names = _token_names(token_env_vars)
    token = _get_token(names)
    if not token:
        err("GITHUB_TOKEN not found.")
        raise typer.Exit(1)
    r = _open_repo(repo, search_parent, init_if_missing)
    _ensure_gitignore(r, gitignore_mode, gitignore_source, gitignore_dest)
    if do_commit:
        msg = message or f"{message_prefix}{datetime.now():%Y-%m-%d %H:%M:%S}"
        _stage_and_commit(r, msg, add_mode)
    if branch:
        r.git.checkout(branch)
    try:
        active = branch or r.active_branch.name
    except TypeError:
        err("In detached HEAD state. Skipping sync.")
        raise typer.Exit(1)
    try:
        remote = r.remote(remote_name)
    except ValueError:
        err(f"Remote '{remote_name}' not found.")
        raise typer.Exit(1)
    info("Fetching updates...")
    remote.fetch()
    try:
        branch_obj = r.active_branch
    except TypeError:
        err("In detached HEAD state. Skipping sync.")
        raise typer.Exit(1)
    if not branch_obj.tracking_branch():
        with contextlib.suppress(Exception):
            branch_obj.set_tracking_branch(remote.refs[active])
    info(f"Pulling latest changes into '{active}'...")
    remote.pull()
    gh_user = github_user or _github_login(token, None)
    parsed = _parse_github_url(remote.url)
    if not parsed:
        err(f"Could not parse GitHub remote URL: {remote.url}")
        raise typer.Exit(1)
    owner, name = parsed
    if owner.lower() == gh_user.lower():
        if r.is_dirty(untracked_files=True) and not allow_dirty:
            err("Uncommitted local changes. Please commit before pushing.")
            raise typer.Exit(1)
        _push_remote(r, remote_name, active, token_auth, token, gh_user, token_url_format, set_upstream)
    else:
        if not push_to_fork:
            info("You are not the owner and --no-push-to-fork was given.")
            return
        url = _fork_repo(token, owner, name)
        if fork_remote_name in [rm.name for rm in r.remotes]:
            r.remote(fork_remote_name).set_url(url)
        else:
            r.create_remote(fork_remote_name, url)
        ok(f"Using fork remote '{fork_remote_name}': {url}")
        _push_remote(r, fork_remote_name, active, fork_token_auth, token, gh_user, token_url_format, set_upstream)
    ok("Successfully synced.")


def _git_clone_one(slug: str, output_dir: Path) -> tuple[str, bool, str]:
    from git import GitCommandError, Repo
    from git.exc import InvalidGitRepositoryError

    if not _is_valid_slug(slug):
        return slug, False, f"Invalid format: {slug} (expected user/repo)"
    owner, repo = slug.split("/")
    dest = output_dir / owner / repo
    if dest.exists():
        try:
            Repo(dest)
            return slug, True, f"Already exists: {dest}"
        except InvalidGitRepositoryError:
            return slug, False, f"Directory exists but is not a git repo: {dest}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/{slug}.git"
    try:
        Repo.clone_from(url, dest, depth=1, single_branch=True)
        return slug, True, f"Successfully cloned to {dest}"
    except GitCommandError as exc:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        return slug, False, f"Clone failed: {str(exc).strip()}"
    except Exception as exc:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        return slug, False, f"Error: {exc!s}"


def _zip_download_one(slug: str, output_dir: Path, timeout: int) -> tuple[str, bool, str]:
    import requests

    if not _is_valid_slug(slug):
        return slug, False, f"Invalid format: {slug}"
    owner, repo = slug.split("/")
    dest = output_dir / owner / repo
    if dest.exists():
        return slug, True, f"Already exists: {dest}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://api.github.com/repos/{slug}/zipball"
    try:
        resp = requests.get(url, timeout=timeout, stream=True)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            top_dir = zf.namelist()[0].split("/")[0]
            tmp = dest.parent / f"_temp_{repo}"
            zf.extractall(tmp)
            inner = tmp / top_dir
            if inner.exists():
                dest.mkdir(parents=True, exist_ok=True)
                for item in inner.iterdir():
                    shutil.move(str(item), str(dest / item.name))
                shutil.rmtree(tmp)
            else:
                shutil.move(str(tmp), str(dest))
        return slug, True, f"Successfully downloaded to {dest}"
    except Exception as exc:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        return slug, False, f"Error: {exc!s}"


def _dulwich_size_check(slug: str, max_bytes: int) -> tuple[bool, int]:
    import requests

    try:
        resp = requests.get(f"https://api.github.com/repos/{slug}", timeout=10)
        if resp.status_code == 200:
            raw = resp.json().get("size", 0)
            size_kb = int(raw) if isinstance(raw, (int, float, str)) else 0
            size_bytes = size_kb * 1024
            return size_bytes <= max_bytes, size_bytes
        return True, 0
    except Exception:
        return True, 0


def _dulwich_clone_one(slug: str, output_dir: Path, max_bytes: int) -> tuple[str, bool, str]:
    from dulwich import porcelain
    from dulwich.errors import NotGitRepository
    from dulwich.repo import Repo as DulwichRepo

    if not _is_valid_slug(slug):
        return slug, False, f"Invalid format: {slug} (expected user/repo)"
    owner, repo = slug.split("/")
    dest = output_dir / owner / repo
    if dest.exists():
        try:
            DulwichRepo(str(dest))
            return slug, True, f"Already exists: {dest}"
        except NotGitRepository:
            return slug, False, f"Directory exists but is not a git repo: {dest}"
    fits, size_bytes = _dulwich_size_check(slug, max_bytes)
    if not fits:
        return slug, False, f"Too large ({_human_size(size_bytes)} > {max_bytes // (1024 * 1024)}MB)"
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/{slug}.git"
    try:
        porcelain.clone(url, str(dest), depth=1)
        return slug, True, f"Successfully cloned to {dest} ({_human_size(size_bytes)})"
    except Exception as exc:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        return slug, False, f"Clone failed: {exc!s}"


def _sparse_clone_one(url: str, output_dir: Path, extensions: list[str], timeout: int = 300) -> tuple[str, bool, str]:
    try:
        parsed = urlparse(url)
        name = Path(parsed.path).stem
        dest = output_dir / name
        subprocess.run(
            ["git", "clone", "--filter=blob:none", "--sparse", url, str(dest)],
            check=True,
            capture_output=True,
            timeout=timeout,
        )
        subprocess.run(
            ["git", "-C", str(dest), "sparse-checkout", "init", "--no-cone"],
            check=True,
            capture_output=True,
        )
        patterns = [f"**/*{(ext if ext.startswith('.') else '.' + ext)}" for ext in extensions]
        subprocess.run(
            ["git", "-C", str(dest), "sparse-checkout", "set", *patterns],
            check=True,
            capture_output=True,
        )
        return url, True, f"Successfully cloned {name}"
    except Exception as exc:
        return url, False, f"Failed: {exc!s}"


@app.command("clone")
def cmd_clone(
    file: Path = typer.Argument(Path("repos.txt")),
    output: Path = typer.Option(Path("repos"), "-o", "--output"),
    workers: int = typer.Option(8, "-w", "--workers"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    repos = _load_repo_list(file)
    info(f"Found {len(repos)} repositories to clone")
    if dry_run:
        info("Dry run - would clone:")
        for slug in repos:
            if _is_valid_slug(slug):
                owner, repo = slug.split("/")
                dest = output / owner / repo
                flag = "EXISTS" if dest.exists() else "NEW"
                console.print(f"  [{flag}] {slug} -> {dest}")
            else:
                console.print(f"  [INVALID] {slug}")
        return
    counters = {"ok": 0, "existed": 0, "failed": 0}

    def handle(slug: str, ok_flag: bool, msg: str) -> None:
        if ok_flag and "Already exists" in msg:
            counters["existed"] += 1
            console.print(f"[yellow]⏭[/yellow]  {slug}: {msg}")
        elif ok_flag:
            counters["ok"] += 1
            console.print(f"[green]✓[/green] {slug}: {msg}")
        else:
            counters["failed"] += 1
            console.print(f"[red]✗[/red] {slug}: {msg}")

    info(f"Cloning with {workers} parallel workers to {output.absolute()}")
    with Pool(processes=workers) as pool:
        jobs = [(slug, pool.apply_async(_git_clone_one, (slug, output))) for slug in repos]
        for slug, async_res in jobs:
            try:
                _, ok_flag, msg = async_res.get()
                handle(slug, ok_flag, msg)
            except Exception as exc:
                err(f"{slug}: Unexpected error: {exc!s}")
    console.rule("Summary")
    console.print(f"[green]✓[/green] Successfully cloned: {counters['ok']}")
    console.print(f"[yellow]⏭[/yellow]  Already existed: {counters['existed']}")
    console.print(f"[red]✗[/red] Failed: {counters['failed']}")


@app.command("zip-download")
def cmd_zip_download(
    file: Path = typer.Argument(Path("repos.txt")),
    output: Path = typer.Option(Path("repos"), "-o", "--output"),
    workers: int = typer.Option(8, "-w", "--workers"),
    timeout: int = typer.Option(30, "--timeout"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    repos = _load_repo_list(file)
    info(f"Found {len(repos)} repositories to download")
    if dry_run:
        for slug in repos:
            if _is_valid_slug(slug):
                owner, repo = slug.split("/")
                dest = output / owner / repo
                flag = "EXISTS" if dest.exists() else "NEW"
                console.print(f"  [{flag}] {slug} -> {dest}")
            else:
                console.print(f"  [INVALID] {slug}")
        return
    counters = {"ok": 0, "existed": 0, "failed": 0}

    def handle(slug: str, ok_flag: bool, msg: str) -> None:
        if ok_flag and "Already exists" in msg:
            counters["existed"] += 1
            console.print(f"[yellow]⏭[/yellow]  {slug}: {msg}")
        elif ok_flag:
            counters["ok"] += 1
            console.print(f"[green]✓[/green] {slug}: {msg}")
        else:
            counters["failed"] += 1
            console.print(f"[red]✗[/red] {slug}: {msg}")

    info(f"Downloading with {workers} parallel workers to {output.absolute()}")
    with Pool(processes=workers) as pool:
        jobs = [(slug, pool.apply_async(_zip_download_one, (slug, output, timeout))) for slug in repos]
        for slug, async_res in jobs:
            try:
                _, ok_flag, msg = async_res.get()
                handle(slug, ok_flag, msg)
            except Exception as exc:
                err(f"{slug}: Unexpected error: {exc!s}")
        pool.close()
        pool.join()
    console.rule("Summary")
    console.print(f"[green]✓[/green] Successfully downloaded: {counters['ok']}")
    console.print(f"[yellow]⏭[/yellow]  Already existed: {counters['existed']}")
    console.print(f"[red]✗[/red] Failed: {counters['failed']}")


@app.command("dulwich-clone")
def cmd_dulwich_clone(
    file: Path = typer.Argument(Path("repos.txt")),
    output: Path = typer.Option(Path("repos"), "-o", "--output"),
    workers: int = typer.Option(8, "-w", "--workers"),
    max_size: int = typer.Option(5, "--max-size"),
    no_cleanup: bool = typer.Option(False, "--no-cleanup"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    max_bytes = max_size * 1024 * 1024
    repos = _load_repo_list(file)
    info(f"Found {len(repos)} repositories to clone")
    info(f"Max repo size: {max_size}MB")
    if dry_run:
        for slug in repos:
            if _is_valid_slug(slug):
                owner, repo = slug.split("/")
                dest = output / owner / repo
                fits, size = _dulwich_size_check(slug, max_bytes)
                if dest.exists():
                    console.print(f"  [EXISTS] {slug} -> {dest}")
                elif not fits:
                    console.print(f"  [TOO LARGE] {slug} ({_human_size(size)})")
                else:
                    console.print(f"  [OK] {slug} -> {dest} ({_human_size(size)})")
            else:
                console.print(f"  [INVALID] {slug}")
        return
    counters = {"ok": 0, "existed": 0, "failed": 0}
    success_slugs: set[str] = set()

    def handle(slug: str, ok_flag: bool, msg: str) -> None:
        if ok_flag and "Already exists" in msg:
            counters["existed"] += 1
            success_slugs.add(slug)
            console.print(f"[yellow]⏭[/yellow]  {slug}: {msg}")
        elif ok_flag:
            counters["ok"] += 1
            success_slugs.add(slug)
            console.print(f"[green]✓[/green] {slug}: {msg}")
        else:
            counters["failed"] += 1
            console.print(f"[red]✗[/red] {slug}: {msg}")

    with Pool(processes=workers) as pool:
        jobs = [(slug, pool.apply_async(_dulwich_clone_one, (slug, output, max_bytes))) for slug in repos]
        for slug, async_res in jobs:
            try:
                _, ok_flag, msg = async_res.get()
                handle(slug, ok_flag, msg)
            except Exception as exc:
                err(f"{slug}: Unexpected error: {exc!s}")
    if not no_cleanup and success_slugs:
        remaining = [r for r in _load_repo_list(file) if r not in success_slugs]
        file.write_text("\n".join(remaining) + ("\n" if remaining else ""))
        info(f"Removed {len(success_slugs)} repos from {file}")
    console.rule("Summary")
    console.print(f"[green]✓[/green] Successfully cloned: {counters['ok']}")
    console.print(f"[yellow]⏭[/yellow]  Already existed: {counters['existed']}")
    console.print(f"[red]✗[/red] Failed: {counters['failed']}")


@app.command("fork")
def cmd_fork(repo: str = typer.Argument(..., help="user/repo or full GitHub URL")) -> None:
    from git import Repo
    from github import Github, GithubException
    from github.GithubException import UnknownObjectException

    raw = repo
    slug = raw.replace("https://github.com/", "").rstrip("/") if raw.startswith("https://github.com/") else raw
    if "/" not in slug:
        err("Use format 'user/repo'")
        raise typer.Exit(1)
    env_path = Path.home() / ".env"
    if not env_path.exists():
        env_path.write_text("# GitHub Personal Access Token\nGITHUB_TOKEN=your_token_here\n")
        warn(f"Created {env_path}. Please add your token.")
        raise typer.Exit(1)
    _load_dotenv()
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        err("GITHUB_TOKEN not set.")
        raise typer.Exit(1)
    gh = Github(token)
    user = gh.get_user()
    ok(f"Authenticated as: {user.login}")
    try:
        original = gh.get_repo(slug)
        ok(f"Found original repo: {original.full_name}")
        try:
            existing = user.get_repo(original.name)
            ok(f"Repository already forked: {existing.clone_url}")
            fork = existing
        except UnknownObjectException:
            info(f"Forking {slug}...")
            fork = original.create_fork()
            ok(f"Fork created: {fork.clone_url}")
    except GithubException as exc:
        err(f"Error forking repository: {exc}")
        raise typer.Exit(1)
    repo_name = fork.name
    clone_url = fork.clone_url
    info(f"Cloning {clone_url}...")
    try:
        local = Repo.clone_from(clone_url, repo_name)
        ok(f"Cloned to: ./{repo_name}")
    except Exception as exc:
        err(f"Error cloning: {exc}")
        raise typer.Exit(1)
    upstream_url = f"https://github.com/{slug}.git"
    info(f"Adding upstream remote: {upstream_url}")
    upstream = local.create_remote("upstream", upstream_url)
    default_branch = fork.default_branch
    upstream.fetch()
    local.git.branch(f"--set-upstream-to=upstream/{default_branch}", default_branch)
    ok("Setup complete!")
    for remote in local.remotes:
        console.print(f"  {remote.name}: {remote.url}")


@app.command("gclone")
def cmd_gclone(
    file: Path = typer.Argument(Path("repos.txt")),
    max_size: int = typer.Option(100, "--max-size"),
    token: Optional[str] = typer.Option(None, "--token"),
    remaining_file: Path = typer.Option(Path("remained"), "--remaining-file"),
) -> None:
    lines = file.read_text(encoding="utf-8").splitlines(keepends=False)
    tok = token or os.getenv("GITHUB_TOKEN")
    too_large: list[str] = []
    total = len(lines)
    for idx, line in enumerate(lines):
        console.print(f"{idx}/{total}")
        owner, repo = _parse_gh_slug(line)
        if not owner or not repo:
            err(f"Invalid GitHub repository format: '{line}'")
            too_large.append(line)
            continue
        info(f"Analyzing repository: {owner}/{repo}")
        size_mb = _gh_size_mb(owner, repo, tok)
        if size_mb is not None and size_mb <= max_size:
            info(f"size: {size_mb} MB")
            destination = Path.cwd() / repo
            if destination.exists():
                warn(f"Destination already exists: {destination}")
                continue
            _cli_git_clone(owner, repo, destination)
        else:
            if size_mb is not None:
                info(f"Skipping (size {size_mb} MB > {max_size} MB)")
            too_large.append(line)
    remaining_file.write_text("\n".join(too_large), encoding="utf-8")
    info(f"Wrote {len(too_large)} remaining entries to {remaining_file}")


def _parse_gh_slug(text: str) -> tuple[Optional[str], Optional[str]]:
    text = text.strip()
    if "/" in text and not text.startswith("http"):
        parts = text.split("/")
        if len(parts) == 2 and parts[0] and parts[1]:
            return parts[0], parts[1]
        return None, None
    try:
        parsed = urlparse(text)
        if parsed.netloc.lower() in {"github.com", "www.github.com"}:
            bits = [p for p in parsed.path.split("/") if p]
            if len(bits) == 2:
                return bits[0], bits[1]
    except Exception:
        pass
    return None, None


@app.command("get-zip")
def cmd_get_zip(
    repo: str = typer.Argument(..., help="user/repo"),
    branch: str = typer.Option("main", "--branch", "-b"),
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
) -> None:
    import requests
    from github import Github

    _load_dotenv()
    try:
        owner, name = repo.split("/")
    except ValueError:
        err("Repository must be in format 'username/repo'")
        raise typer.Exit(1)
    token = os.getenv("GITHUB_TOKEN")
    gh = Github(token)
    gh_repo = gh.get_repo(f"{owner}/{name}")
    zip_url = gh_repo.get_zipball_url(branch)
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3.raw"}
    resp = requests.get(zip_url, headers=headers, stream=True)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))
    info(f"Download size: {total / (1024 * 1024):.2f} MB ({total:,} bytes)")
    out_name = str(output) if output else f"{name}-{branch}.zip"
    with open(out_name, "wb") as f:
        for piece in resp.iter_content(chunk_size=8192):
            if piece:
                f.write(piece)
    ok(f"Downloaded: {out_name}")


@app.command("sparse")
def cmd_sparse(
    items: list[str] = typer.Argument(..., help="Extensions and URLs, any order"),
    output: Path = typer.Option(Path("cloned_repos"), "-o", "--output"),
    workers: int = typer.Option(4, "-w", "--workers"),
) -> None:
    extensions: list[str] = []
    urls: list[str] = []
    for token in items:
        if token.startswith(("http://", "https://")) or token.endswith(".git"):
            urls.append(token)
        else:
            extensions.append(token)
    if not extensions or not urls:
        err("Must provide at least one extension and one repository URL")
        raise typer.Exit(1)
    output.mkdir(exist_ok=True)
    info(f"Extensions to clone: {', '.join(extensions)}")
    info(f"Repositories: {len(urls)}")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_sparse_clone_one, url, output, extensions): url for url in urls}
        for future in as_completed(futures):
            url, ok_flag, msg = future.result()
            marker = "[green]✓[/green]" if ok_flag else "[red]✗[/red]"
            console.print(f"{marker} {url}: {msg}")


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        err("Interrupted by user.")
        sys.exit(130)


if __name__ == "__main__":
    main()
