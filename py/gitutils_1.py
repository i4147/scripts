#!/data/data/com.termux/files/usr/bin/python
from __future__ import annotations
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence
from urllib import error, request


@dataclass
class CommitInfo:
    hash: str
    author: str
    email: str
    date: str
    subject: str


@dataclass
class FileChange:
    status: str
    path: str
    old_path: str | None
    insertions: int | None
    deletions: int | None


@dataclass
class DiffReport:
    repo: str
    from_commit: CommitInfo
    to_commit: CommitInfo
    files: list[FileChange]
    patch: str


@dataclass
class RepoScan:
    path: Path
    dirty: bool
    detail: str


@dataclass
class AddedFilesCommit:
    sha: str
    short: str
    author_name: str
    author_email: str
    authored_at: str
    message: str
    added: list[str]
    modified: list[str]
    deleted: list[str]
    renamed: list[dict[str, str]]


def run(
    cmd: Sequence[str], cwd: Path | None = None, check: bool = True, timeout: int = 60
) -> subprocess.CompletedProcess[str]:
    try:
        cp = subprocess.run(
            list(cmd), cwd=str(cwd) if cwd else None, capture_output=True, text=True, check=False, timeout=timeout
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"command not found: {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"command timed out: {' '.join(cmd)}") from exc
    if check and cp.returncode != 0:
        msg = (cp.stderr or cp.stdout or "").strip() or f"command failed: {' '.join(cmd)}"
        raise RuntimeError(msg)
    return cp


def git(args: Sequence[str], cwd: Path | None = None, check: bool = True, timeout: int = 60) -> str:
    return run(["git", *args], cwd, check, timeout).stdout


def is_git_repo(path: Path) -> bool:
    return (path / ".git").is_dir()


def find_git_repos(root: Path) -> list[Path]:
    result: list[Path] = []
    for current, dirs, _ in os.walk(root):
        p = Path(current)
        if (p / ".git").is_dir():
            result.append(p)
            dirs[:] = []
    return result


def current_branch(repo: Path) -> str:
    out = git(["branch", "--show-current"], repo, check=False).strip()
    if out:
        return out
    out = git(["rev-parse", "--abbrev-ref", "HEAD"], repo).strip()
    if out == "HEAD":
        raise RuntimeError("detached HEAD")
    return out


def detect_main_branch(repo: Path) -> str:
    cp = run(["git", "remote", "show", "origin"], repo, check=False)
    if cp.returncode == 0:
        for line in cp.stdout.splitlines():
            if "HEAD branch" in line:
                return line.split(":", 1)[1].strip()
    branches = git(["branch", "-l"], repo).splitlines()
    names = [b.strip().replace("*", "").strip() for b in branches if b.strip()]
    for name in ("main", "master"):
        if name in names:
            return name
    return "main"


def load_token(env_file: Path | None = None) -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token
    path = (env_file or (Path.home() / ".env")).expanduser()
    if not path.exists():
        raise RuntimeError(f"GITHUB_TOKEN not found and {path} does not exist")
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[7:].lstrip()
        if s.startswith("GITHUB_TOKEN="):
            value = s.split("=", 1)[1].strip().strip("\"'")
            if value:
                return value
    raise RuntimeError(f"GITHUB_TOKEN not found in {path}")


def github_request(token: str, method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "git-helper/1.0")
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
            return json.loads(body) if body else {}
    except error.HTTPError as exc:
        body = exc.read().decode()
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"message": body}
        raise RuntimeError(f"GitHub API {exc.code}: {parsed.get('message', body)}") from exc


def create_github_repo(
    token: str, name: str, private: bool, description: str | None, auto_init: bool
) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name, "private": private, "auto_init": auto_init}
    if description:
        payload["description"] = description
    try:
        return github_request(token, "POST", "https://api.github.com/user/repos", payload)
    except RuntimeError as exc:
        if "422" in str(exc):
            user = github_request(token, "GET", "https://api.github.com/user")["login"]
            return {
                "clone_url": f"https://github.com/{user}/{name}.git",
                "ssh_url": f"git@github.com:{user}/{name}.git",
                "html_url": f"https://github.com/{user}/{name}",
            }
        raise


def parse_github_remote(url: str) -> tuple[str, str] | None:
    patterns = [
        r"^git@github\.com:([^/]+)/(.+?)(?:\.git)?/?$",
        r"^https?://(?:[^@/]+@)?github\.com/([^/]+)/(.+?)(?:\.git)?/?$",
    ]
    for pattern in patterns:
        m = re.match(pattern, url)
        if m:
            return m.group(1), m.group(2)
    return None


def ensure_remote(repo: Path, url: str, remote: str = "origin") -> None:
    cp = run(["git", "remote", "get-url", remote], repo, check=False)
    if cp.returncode == 0:
        if cp.stdout.strip() != url:
            run(["git", "remote", "set-url", remote, url], repo)
    else:
        run(["git", "remote", "add", remote, url], repo)


def commit_all(repo: Path, message: str) -> bool:
    run(["git", "add", "-A"], repo)
    cp = run(["git", "status", "--porcelain"], repo)
    if not cp.stdout.strip():
        return False
    run(["git", "commit", "-m", message], repo)
    return True


def push_branch(repo: Path, branch: str, remote: str = "origin", force: bool = False) -> None:
    args = ["git", "push", "-u", remote, branch]
    if force:
        args.insert(2, "--force-with-lease")
    run(args, repo)


def commit_info(repo: Path, rev: str) -> CommitInfo:
    fmt = "%an%x00%ae%x00%ad%x00%s"
    out = git(["show", "-s", f"--format={fmt}", rev], repo).strip()
    author, email, date, subject = out.split("\x00")
    return CommitInfo(rev, author, email, date, subject)


def diff_files(repo: Path, old: str, new: str) -> list[FileChange]:
    name_status = git(["diff", "--name-status", old, new], repo).splitlines()
    numstat = git(["diff", "--numstat", old, new], repo).splitlines()
    stats: dict[str, tuple[int | None, int | None]] = {}
    for line in numstat:
        parts = line.split("\t")
        if len(parts) == 3:
            ins, del_, path = parts
            stats[path] = (None if ins == "-" else int(ins), None if del_ == "-" else int(del_))
    changes: list[FileChange] = []
    for line in name_status:
        parts = line.split("\t")
        if not parts:
            continue
        status = parts[0]
        old_path: str | None = None
        if status.startswith(("R", "C")) and len(parts) == 3:
            old_path, path = parts[1], parts[2]
        elif len(parts) > 1:
            path = parts[1]
        else:
            continue
        ins, del_ = stats.get(path, (None, None))
        changes.append(FileChange(status, path, old_path, ins, del_))
    return changes


def cmd_diff_report(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    hashes = git(["log", "-2", "--format=%H"], repo).strip().splitlines()
    if len(hashes) < 2:
        raise RuntimeError("Repository needs at least 2 commits to diff.")
    new, old = hashes[0], hashes[1]
    report = DiffReport(
        str(repo),
        commit_info(repo, old),
        commit_info(repo, new),
        diff_files(repo, old, new),
        git(["diff", old, new], repo),
    )
    out = Path(args.output)
    out.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
    print(f"Wrote diff report: {out}")
    return 0


def cmd_merge_squash(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    current = current_branch(repo)
    branch = args.branch
    cp = run(["git", "cherry", "-v", current, branch], repo)
    subjects: list[str] = []
    for line in cp.stdout.splitlines():
        parts = line.split(" ")
        if len(parts) > 2:
            subjects.append(" ".join(parts[2:]))
    reviewer = args.reviewer or f"{input('Reviewer name: ')}<{input('Reviewer email: ')}>"
    message = "\n".join(subjects) + f"\n\nReviewed By: {reviewer}"
    run(["git", "merge", "--squash", "--no-log", branch], repo)
    run(["git", "commit", "-m", message], repo)
    print("Successfully merged!")
    return 0


def scan_repo(path: Path) -> RepoScan:
    try:
        cp = run(["git", "status", "--porcelain"], path, check=False, timeout=10)
        if cp.returncode != 0:
            return RepoScan(path, False, f"Git error: {cp.stderr.strip()}")
        lines = [line for line in cp.stdout.splitlines() if line.strip()]
        if not lines:
            return RepoScan(path, False, "Clean")
        detail = ", ".join(lines[:5])
        if len(lines) > 5:
            detail += f" (+{len(lines) - 5} more)"
        return RepoScan(path, True, detail)
    except Exception as exc:
        return RepoScan(path, False, f"Error: {exc}")


def cmd_scan_changes(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    repos = find_git_repos(root)
    if not repos:
        print("No git repositories found.")
        return 0
    with ProcessPoolExecutor(max_workers=args.jobs or None) as pool:
        results = list(pool.map(scan_repo, repos))
    dirty = [r for r in results if r.dirty]
    for r in results:
        if r.dirty:
            print(f"✗ {r.path.name}: CHANGES DETECTED")
            print(f"  └─ {r.detail}")
        else:
            print(f"✓ {r.path.name}: No changes")
            if r.detail != "Clean":
                print(f"  └─ {r.detail}")
    if dirty:
        print(f"Found {len(dirty)} repository(ies) with changes")
    else:
        print("All repositories are clean")
    return 0


def pull_repo(repo: Path) -> tuple[Path, bool, str]:
    try:
        branch = current_branch(repo)
        cp = run(["git", "remote"], repo, check=False)
        if cp.returncode != 0 or not cp.stdout.strip():
            return repo, False, "No remote configured"
        remote = cp.stdout.splitlines()[0]
        run(["git", "pull", remote, branch], repo, timeout=120)
        return repo, True, "Pulled successfully"
    except Exception as exc:
        return repo, False, str(exc)


def cmd_pull_all(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    repos = find_git_repos(root)
    if not repos:
        print("No git repositories found.")
        return 0
    with ProcessPoolExecutor(max_workers=args.jobs or None) as pool:
        results = list(pool.map(pull_repo, repos))
    ok = [r for r in results if r[1]]
    bad = [r for r in results if not r[1]]
    for repo, _, msg in ok:
        print(f"✅ {repo.relative_to(root)}: {msg}")
    for repo, _, msg in bad:
        print(f"❌ {repo.relative_to(root)}: {msg}")
    return 0


def process_new_pull(repo: Path, token: str) -> tuple[Path, bool, str]:
    try:
        remotes = run(["git", "remote"], repo, check=False).stdout.strip()
        if remotes:
            branch = current_branch(repo)
            remote = remotes.splitlines()[0]
            run(["git", "pull", remote, branch], repo, timeout=120)
            return repo, True, "Pulled successfully"
        info = create_github_repo(token, repo.name, False, f"Repository for {repo.name}", False)
        url = info.get("clone_url") or info.get("ssh_url")
        if not url:
            return repo, False, "Could not determine remote URL"
        ensure_remote(repo, url)
        branch = current_branch(repo)
        push_branch(repo, branch)
        return repo, True, f"Created and pushed to {url}"
    except Exception as exc:
        return repo, False, str(exc)


def cmd_pull_new(args: argparse.Namespace) -> int:
    token = load_token(Path(args.env_file) if args.env_file else None)
    root = Path(args.path).resolve()
    repos = find_git_repos(root)
    if not repos:
        print("No git repositories found.")
        return 0
    with ProcessPoolExecutor(max_workers=args.jobs or None) as pool:
        results = list(pool.map(process_new_pull, repos, [token] * len(repos)))
    ok = [r for r in results if r[1]]
    bad = [r for r in results if not r[1]]
    for repo, _, msg in ok:
        print(f"✅ {repo.relative_to(root)}: {msg}")
    for repo, _, msg in bad:
        print(f"❌ {repo.relative_to(root)}: {msg}")
    return 0


def cmd_create_repo(args: argparse.Namespace) -> int:
    token = load_token(Path(args.env_file) if args.env_file else None)
    source = Path(args.source).resolve()
    name = args.name or source.name
    info = create_github_repo(token, name, args.private, args.description, args.auto_init)
    url = info.get("clone_url") if args.protocol == "https" else info.get("ssh_url")
    if not url:
        raise RuntimeError("Could not determine remote URL")
    if args.push:
        os.chdir(source)
        if not is_git_repo(source):
            run(["git", "init"], source)
        if args.git_user:
            run(["git", "config", "user.name", args.git_user], source)
        if args.git_email:
            run(["git", "config", "user.email", args.git_email], source)
        commit_all(source, args.commit_message)
        if args.rename_branch:
            run(["git", "branch", "-M", args.branch], source)
        ensure_remote(source, url, args.remote)
        push_branch(source, args.branch, args.remote)
    print(info.get("html_url", url))
    return 0


def cmd_squash(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    n = args.n
    if n <= 0:
        raise RuntimeError("N must be > 0")
    run(["git", "add", "-A"], repo)
    cp = run(["git", "status", "--porcelain"], repo)
    if cp.stdout.strip():
        run(["git", "commit", "-m", "auto-commit before squash", "--no-verify"], repo)
    head = git(["rev-parse", "HEAD"], repo).strip()
    commits = git(["rev-list", f"--max-count={n}", "--reverse", "HEAD"], repo).splitlines()
    if len(commits) < n:
        raise RuntimeError(f"Repository has fewer than {n} commits")
    base = git(["rev-parse", f"HEAD~{n}"], repo).strip()
    patch = Path(args.patch_file).resolve()
    meta = Path(args.meta_file).resolve()
    diff = run(["git", "diff", "--binary", f"{base}..{head}"], repo).stdout
    patch.write_text(diff, encoding="utf-8")
    meta.write_text(json.dumps({"base": base, "head": head, "commits": commits}, indent=2), encoding="utf-8")
    if args.dry_run:
        print(f"Would reset to {base}, apply {patch}, and commit")
        return 0
    run(["git", "reset", "--hard", base], repo)
    run(["git", "apply", "--index", str(patch)], repo)
    run(["git", "add", "-A"], repo)
    subjects = git(["log", "--format=%h-%s", f"{base}..{head}"], repo).strip().splitlines()
    message = f"Squash {n} commits: " + "; ".join(subjects)
    run(["git", "commit", "-m", message], repo)
    print("Done")
    return 0


def cmd_fix(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    run(["git", "fetch", "origin"], repo)
    upstream = None
    for ref in ("origin/master", "origin/main"):
        cp = run(["git", "rev-parse", "--verify", ref], repo, check=False)
        if cp.returncode == 0:
            upstream = ref
            break
    if not upstream:
        raise RuntimeError("Neither origin/master nor origin/main exists")
    branch = current_branch(repo)
    cp = run(["git", "rebase", "--onto", upstream, "HEAD", branch], repo, check=False)
    if cp.returncode != 0:
        run(["git", "rebase", "--abort"], repo, check=False)
        raise RuntimeError(cp.stderr.strip() or "Rebase failed")
    run(["git", "push", "--force-with-lease", "origin", branch], repo)
    print("Successfully synced branch")
    return 0


def cmd_gitignore_add(args: argparse.Namespace) -> int:
    line = args.line.strip()
    if not line:
        raise RuntimeError("line cannot be empty")
    paths = [Path(p).resolve() for p in (args.paths or ["."])]
    files: list[Path] = []
    for path in paths:
        if path.is_file() and path.name == ".gitignore":
            files.append(path)
        elif path.is_dir():
            files.extend(p for p in path.rglob(".gitignore") if p.is_file())
    modified = 0
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            if line in text.splitlines():
                continue
            if text and not text.endswith("\n"):
                text += "\n"
            text += line + "\n"
            path.write_text(text, encoding="utf-8")
            modified += 1
            print(f"Updated {path}")
        except Exception as exc:
            print(f"Failed {path}: {exc}", file=sys.stderr)
    print(f"Modified {modified} file(s)")
    return 0


def cmd_keep_main(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    if not is_git_repo(repo):
        raise RuntimeError("Not a git repository")
    main = detect_main_branch(repo)
    branches = [b.strip().replace("*", "").strip() for b in git(["branch", "-l"], repo).splitlines() if b.strip()]
    for branch in branches:
        if branch != main:
            run(["git", "branch", "-D", branch], repo, check=False)
    run(["git", "checkout", main], repo)
    run(["git", "checkout", "--orphan", "temp_branch"], repo)
    run(["git", "add", "-A"], repo)
    run(["git", "commit", "-m", "Squashed history, keeping last commit"], repo)
    run(["git", "branch", "-D", main], repo)
    run(["git", "branch", "-m", main], repo)
    print("Cleanup completed")
    return 0


def restore_repo(repo: Path) -> tuple[Path, bool, str]:
    try:
        run(["git", "restore", "."], repo)
        return repo, True, "Restored"
    except Exception as exc:
        return repo, False, str(exc)


def cmd_restore(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    repos = find_git_repos(root)
    if not repos:
        print("No git repositories found.")
        return 0
    with ProcessPoolExecutor(max_workers=args.jobs or None) as pool:
        results = list(pool.map(restore_repo, repos))
    for repo, ok, msg in results:
        mark = "✅" if ok else "❌"
        print(f"{mark} {repo.relative_to(root)}: {msg}")
    return 0


def cmd_added_files(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    revs = git(["rev-list", args.branch], repo).splitlines()
    if args.max_count:
        revs = revs[: args.max_count]
    results: list[AddedFilesCommit] = []
    for sha in revs:
        cp = run(["git", "show", "-s", "--format=%H%x1f%an%x1f%ae%x1f%aI%x1f%s", sha], repo)
        parts = cp.stdout.strip().split("\x1f")
        if len(parts) < 5:
            continue
        h, an, ae, ad, msg = parts
        diff = run(["git", "diff-tree", "--no-commit-id", "--name-status", "-r", "-M", "--root", sha], repo).stdout
        added: list[str] = []
        modified: list[str] = []
        deleted: list[str] = []
        renamed: list[dict[str, str]] = []
        for line in diff.splitlines():
            cols = line.split("\t")
            if not cols:
                continue
            status = cols[0]
            if status.startswith("A") and len(cols) > 1:
                added.append(cols[1])
            elif status.startswith("M") and len(cols) > 1:
                modified.append(cols[1])
            elif status.startswith("D") and len(cols) > 1:
                deleted.append(cols[1])
            elif status.startswith(("R", "C")) and len(cols) > 2:
                renamed.append({"from": cols[1], "to": cols[2]})
        results.append(AddedFilesCommit(h, h[:8], an, ae, ad, msg, added, modified, deleted, renamed))
    out = Path(args.output)
    out.write_text(json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8")
    print(f"Wrote {len(results)} commits to {out}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    revs = git(["rev-list", "HEAD"], repo).splitlines()
    result: dict[str, list[str]] = {}
    for sha in revs:
        diff = run(["git", "diff-tree", "--no-commit-id", "--name-status", "-r", "-M", "--root", sha], repo).stdout
        added: list[str] = []
        for line in diff.splitlines():
            cols = line.split("\t")
            if cols and cols[0].startswith("A") and len(cols) > 1:
                added.append(Path(cols[1]).name)
        result[sha[:8]] = sorted(set(added))
    out = Path(args.output)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Wrote {len(result)} commits to {out}")
    return 0


def cmd_auto_commit_push(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    home_ignore = Path.home() / ".gitignore"
    local_ignore = repo / ".gitignore"
    if home_ignore.exists() and not local_ignore.exists():
        shutil.copy2(home_ignore, local_ignore)
    run(["git", "add", "-A"], repo)
    message = datetime.now().strftime("Auto-commit at %Y-%m-%d %H:%M:%S")
    cp = run(["git", "status", "--porcelain"], repo)
    if cp.stdout.strip():
        run(["git", "commit", "-m", message], repo)
    branch = current_branch(repo)
    run(["git", "push", "origin", branch], repo)
    print(f"Pushed to origin/{branch} with message: {message}")
    return 0


def cmd_newrepo(args: argparse.Namespace) -> int:
    token = load_token(Path(args.env_file) if args.env_file else None)
    repo = Path.cwd().resolve()
    name = args.name or repo.name
    user = github_request(token, "GET", "https://api.github.com/user")["login"]
    info = create_github_repo(token, name, args.private, args.description, False)
    url = info.get("clone_url") or info.get("ssh_url")
    if not url:
        raise RuntimeError("Could not determine remote URL")
    if not is_git_repo(repo):
        run(["git", "init", "-b", args.branch], repo)
    if not (repo / ".gitignore").exists() and (Path.home() / ".gitignore").exists():
        shutil.copy2(Path.home() / ".gitignore", repo / ".gitignore")
    commit_all(repo, args.message)
    run(["git", "branch", "-M", args.branch], repo)
    ensure_remote(repo, url)
    push_branch(repo, args.branch)
    print(f"https://github.com/{user}/{name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="git-helper")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("diff-report")
    p.add_argument("repo", nargs="?", default=".")
    p.add_argument("output", nargs="?", default="diff_report.json")
    p.set_defaults(func=cmd_diff_report)
    p = sub.add_parser("merge-squash")
    p.add_argument("branch")
    p.add_argument("--repo", default=".")
    p.add_argument("--reviewer")
    p.set_defaults(func=cmd_merge_squash)
    p = sub.add_parser("scan-changes")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--jobs", type=int)
    p.set_defaults(func=cmd_scan_changes)
    p = sub.add_parser("pull-all")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--jobs", type=int)
    p.set_defaults(func=cmd_pull_all)
    p = sub.add_parser("pull-new")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--env-file")
    p.add_argument("--jobs", type=int)
    p.set_defaults(func=cmd_pull_new)
    p = sub.add_parser("create-repo")
    p.add_argument("--name")
    p.add_argument("--source", default=".")
    p.add_argument("--description")
    p.add_argument("--private", action="store_true")
    p.add_argument("--auto-init", action="store_true")
    p.add_argument("--push", action="store_true")
    p.add_argument("--env-file")
    p.add_argument("--remote", default="origin")
    p.add_argument("--protocol", choices=["https", "ssh"], default="ssh")
    p.add_argument("--branch", default="main")
    p.add_argument("--commit-message", default="Update files")
    p.add_argument("--git-user")
    p.add_argument("--git-email")
    p.add_argument("--rename-branch", action="store_true")
    p.set_defaults(func=cmd_create_repo)
    p = sub.add_parser("squash")
    p.add_argument("n", type=int)
    p.add_argument("--repo", default=".")
    p.add_argument("--patch-file", default="saved_patch.diff")
    p.add_argument("--meta-file", default="saved_patch.meta.json")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_squash)
    p = sub.add_parser("fix")
    p.add_argument("repo", nargs="?", default=".")
    p.set_defaults(func=cmd_fix)
    p = sub.add_parser("gitignore-add")
    p.add_argument("line")
    p.add_argument("paths", nargs="*")
    p.set_defaults(func=cmd_gitignore_add)
    p = sub.add_parser("keep-main")
    p.add_argument("repo", nargs="?", default=".")
    p.set_defaults(func=cmd_keep_main)
    p = sub.add_parser("restore")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--jobs", type=int)
    p.set_defaults(func=cmd_restore)
    p = sub.add_parser("added-files")
    p.add_argument("repo", nargs="?", default=".")
    p.add_argument("output", nargs="?", default="added_files.json")
    p.add_argument("--branch", default="HEAD")
    p.add_argument("--max-count", type=int)
    p.set_defaults(func=cmd_added_files)
    p = sub.add_parser("report")
    p.add_argument("repo", nargs="?", default=".")
    p.add_argument("output", nargs="?", default="added_files.json")
    p.set_defaults(func=cmd_report)
    p = sub.add_parser("auto-commit-push")
    p.add_argument("repo", nargs="?", default=".")
    p.set_defaults(func=cmd_auto_commit_push)
    p = sub.add_parser("newrepo")
    p.add_argument("--name")
    p.add_argument("--private", action="store_true")
    p.add_argument("--description")
    p.add_argument("--message", default="Initial commit")
    p.add_argument("--branch", default="main")
    p.add_argument("--env-file")
    p.set_defaults(func=cmd_newrepo)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
