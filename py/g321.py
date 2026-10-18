from __future__ import annotations
import argparse
import os
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class SubprocessBackend:
    name = "subprocess"

    def __init__(self) -> None:
        pass

    def _run(
        self,
        args: list[str],
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            check=check,
            env=env,
        )

    def is_repo(self) -> bool:
        try:
            self._run(["rev-parse", "--git-dir"])
            return True
        except subprocess.CalledProcessError:
            return False

    def count_commits(self) -> int:
        return int(self._run(["rev-list", "--count", "HEAD"]).stdout.strip())

    def commit_dates(self, count: int) -> list[str]:
        out = self._run(["log", f"-{count}", "--format=%cd", "--date=short"]).stdout
        return [line.strip() for line in out.splitlines() if line.strip()]

    def rev_parse(self, ref: str) -> str:
        return self._run(["rev-parse", ref]).stdout.strip()

    def commit_subject(self, commit: str) -> str:
        return self._run(["log", "-1", "--format=%s", commit]).stdout.strip()

    def commit_message(self, commit: str) -> str:
        return self._run(["log", "-1", "--format=%B", commit]).stdout

    def rebase_interactive(self, count: int, todo_content: str) -> tuple[bool, str]:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as fh:
            fh.write(f"import pathlib, sys\npathlib.Path(sys.argv[1]).write_text({todo_content!r}, encoding='utf-8')\n")
            editor_path = fh.name
        try:
            env = {
                **os.environ,
                "GIT_SEQUENCE_EDITOR": (f"{shlex.quote(sys.executable)} {shlex.quote(editor_path)}"),
            }
            result = subprocess.run(
                ["git", "rebase", "-i", f"HEAD~{count}"],
                capture_output=True,
                text=True,
                env=env,
            )
            if result.returncode != 0:
                return False, result.stderr
            return True, ""
        finally:
            Path(editor_path).unlink(missing_ok=True)

    def amend_date(self, date_str: str) -> tuple[bool, str]:
        result = self._run(
            ["commit", "--amend", "--no-edit", "--date", "-m", date_str],
            check=False,
        )
        return result.returncode == 0, result.stderr

    def push_force_with_lease(self) -> tuple[bool, str]:
        result = self._run(["push", "--force-with-lease"], check=False)
        return result.returncode == 0, result.stderr

    def abort_rebase(self) -> None:
        try:
            self._run(["rebase", "--abort"], check=False)
        except Exception:
            pass


class GitPythonBackend(SubprocessBackend):
    name = "gitpython"

    def __init__(self) -> None:
        try:
            import git
        except ImportError as exc:
            raise RuntimeError("gitpython not installed") from exc
        self._git = git
        self._repo = git.Repo(os.getcwd(), search_parent_directories=True)

    def is_repo(self) -> bool:
        return True

    def count_commits(self) -> int:
        return sum(1 for _ in self._repo.iter_commits("HEAD"))

    def commit_dates(self, count: int) -> list[str]:
        dates: list[str] = []
        for i, c in enumerate(self._repo.iter_commits("HEAD")):
            if i >= count:
                break
            dates.append(c.committed_datetime.strftime("%Y-%m-%d"))
        return dates

    def rev_parse(self, ref: str) -> str:
        return self._repo.commit(ref).hexsha

    def commit_subject(self, commit: str) -> str:
        return self._repo.commit(commit).summary

    def commit_message(self, commit: str) -> str:
        return self._repo.commit(commit).message


class Libgit2Backend(SubprocessBackend):
    name = "libgit2"

    def __init__(self) -> None:
        try:
            import pygit2
        except ImportError as exc:
            raise RuntimeError("pygit2 (libgit2 bindings) not installed") from exc
        discovered = pygit2.discover_repository(os.getcwd())
        if not discovered:
            raise RuntimeError("not inside a git repository")
        self._pygit2 = pygit2
        self._repo = pygit2.Repository(discovered)

    def is_repo(self) -> bool:
        return True

    def count_commits(self) -> int:
        count = 0
        for _ in self._repo.walk(self._repo.head.target):
            count += 1
        return count

    def commit_dates(self, count: int) -> list[str]:
        dates: list[str] = []
        for i, c in enumerate(self._repo.walk(self._repo.head.target)):
            if i >= count:
                break
            dates.append(datetime.fromtimestamp(c.commit_time).strftime("%Y-%m-%d"))
        return dates

    def rev_parse(self, ref: str) -> str:
        return str(self._repo.revparse_single(ref).id)

    def commit_subject(self, commit: str) -> str:
        c = self._repo.revparse_single(commit)
        return c.message.split("\n", 1)[0]

    def commit_message(self, commit: str) -> str:
        c = self._repo.revparse_single(commit)
        return c.message


class DulwichBackend(SubprocessBackend):
    name = "dulwich"

    def __init__(self) -> None:
        try:
            from dulwich.repo import Repo
        except ImportError as exc:
            raise RuntimeError("dulwich not installed") from exc
        self._Repo = Repo
        self._repo = Repo.discover(os.getcwd())

    def is_repo(self) -> bool:
        return True

    def count_commits(self) -> int:
        count = 0
        for _ in self._repo.get_walker():
            count += 1
        return count

    def commit_dates(self, count: int) -> list[str]:
        dates: list[str] = []
        for i, entry in enumerate(self._repo.get_walker()):
            if i >= count:
                break
            dates.append(datetime.fromtimestamp(entry.commit.commit_time).strftime("%Y-%m-%d"))
        return dates

    def rev_parse(self, ref: str) -> str:
        return self._repo[ref.encode()].id.decode()

    def commit_subject(self, commit: str) -> str:
        c = self._repo[commit.encode()]
        return c.message.decode(errors="replace").split("\n", 1)[0]

    def commit_message(self, commit: str) -> str:
        c = self._repo[commit.encode()]
        return c.message.decode(errors="replace")


class PyGithubBackend(SubprocessBackend):
    name = "pygithub"

    def __init__(self) -> None:
        try:
            import github
        except ImportError as exc:
            raise RuntimeError("PyGithub not installed") from exc
        print(
            "warning: PyGithub is remote-API-only; local operations will use subprocess.",
            file=sys.stderr,
        )


_BACKEND_REGISTRY: dict[str, type[SubprocessBackend]] = {
    "subprocess": SubprocessBackend,
    "gitpython": GitPythonBackend,
    "libgit2": Libgit2Backend,
    "dulwich": DulwichBackend,
    "pygithub": PyGithubBackend,
}


def build_backend(name: str) -> SubprocessBackend:
    norm = name.lower()
    if norm == "subprocess":
        return SubprocessBackend()
    if norm == "typer":
        print(
            "warning: 'typer' is a CLI framework, not a git backend; using subprocess.",
            file=sys.stderr,
        )
        return SubprocessBackend()
    if norm == "dulwitch":
        print(
            "warning: 'dulwitch' is not a known backend; did you mean 'dulwich'? Using dulwich.",
            file=sys.stderr,
        )
        norm = "dulwich"
    cls = _BACKEND_REGISTRY.get(norm)
    if cls is None:
        print(
            f"warning: unknown backend {name!r}; using subprocess.",
            file=sys.stderr,
        )
        return SubprocessBackend()
    try:
        return cls()
    except Exception as exc:
        print(
            f"warning: backend {name!r} unavailable ({exc}); using subprocess.",
            file=sys.stderr,
        )
        return SubprocessBackend()


def squash_commits(
    backend: SubprocessBackend,
    count: int,
    commit_date: str | None = None,
    *,
    push: bool = True,
    require_multi_day: bool = True,
) -> bool:
    if count < 2:
        print(
            f"Error: need at least 2 commits to squash, got {count}",
            file=sys.stderr,
        )
        return False
    if not backend.is_repo():
        print("Error: not inside a git repository", file=sys.stderr)
        return False
    total = backend.count_commits()
    if count > total:
        print(
            f"Error: only {total} commit(s) available, cannot squash {count}",
            file=sys.stderr,
        )
        return False
    if require_multi_day:
        dates = backend.commit_dates(count)
        if len(dates) >= 2 and len(set(dates)) == 1:
            print(
                f"Skipping: the last {count} commits all fall on {dates[0]}. Pass --allow-same-day to override.",
                file=sys.stderr,
            )
            return False
    todo: list[str] = []
    for i in range(count):
        h = backend.rev_parse(f"HEAD~{count - 1 - i}")
        subject = backend.commit_subject(h)
        action = "pick" if i == 0 else "squash"
        todo.append(f"{action} {h} {subject}")
    todo_content = "\n".join(todo) + "\n"
    ok, err = backend.rebase_interactive(count, todo_content)
    if not ok:
        print(f"Rebase failed: {err}", file=sys.stderr)
        backend.abort_rebase()
        return False
    if commit_date is None:
        formatted = datetime.now(timezone.utc).strftime("%a,%d%b%Y%H:%M:%S%z")
    else:
        try:
            formatted = datetime.fromisoformat(commit_date.replace("Z", "+00:00")).strftime("%a,%d%b%Y%H:%M:%S%z")
        except ValueError:
            formatted = commit_date
    ok, err = backend.amend_date(formatted)
    if not ok:
        print(f"Failed to amend commit date: {err}", file=sys.stderr)
        return False
    print(f"Successfully squashed {count} commits into one.")
    print(f"Commit date set to: {formatted}")
    if push:
        print("Pushing with --force-with-lease ...")
        ok, err = backend.push_force_with_lease()
        if not ok:
            print(f"Push failed: {err}", file=sys.stderr)
            return False
        print("Push successful.")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Squash the last N commits into one and stamp the date. Only runs when the commits span more than one day."
        ),
    )
    parser.add_argument(
        "count_pos",
        nargs="?",
        type=int,
        default=None,
        help="Number of commits to squash (positional shorthand for -c).",
    )
    parser.add_argument(
        "-c",
        "--count",
        type=int,
        default=3,
        help="Number of commits to squash (default: 3).",
    )
    parser.add_argument(
        "-d",
        "--date",
        default=None,
        help=(
            'Commit date. "today" means now (UTC); an ISO string is parsed; '
            "anything else is passed to git verbatim. Default: now (UTC)."
        ),
    )
    parser.add_argument(
        "-b",
        "--backend",
        default="subprocess",
        choices=[
            "subprocess",
            "pygithub",
            "gitpython",
            "libgit2",
            "dulwich",
            "dulwitch",
            "typer",
        ],
        help=(
            "Git backend. Non-subprocess backends fall back to subprocess "
            "for operations their library cannot do (interactive rebase, "
            "amend, force-with-lease push). Default: subprocess."
        ),
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Skip 'git push --force-with-lease' after squashing.",
    )
    parser.add_argument(
        "--allow-same-day",
        default=True,
        action="store_true",
        help="Squash even when all N commits fall on the same day.",
    )
    args = parser.parse_args(argv)
    backend = build_backend(args.backend)
    if backend.name != args.backend and args.backend not in ("dulwitch",):
        pass
    count = args.count_pos if args.count_pos is not None else args.count
    if args.date and args.date.lower() == "today":
        args.date = None
    ok = squash_commits(
        backend,
        count,
        args.date,
        push=not args.no_push,
        require_multi_day=not args.allow_same_day,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
