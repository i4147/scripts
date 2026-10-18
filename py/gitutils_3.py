#!/data/data/com.termux/files/usr/bin/python
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
class aL:
    pass


@dataclass
class aN:
    pass


@dataclass
class aM:
    pass


@dataclass
class S:
    pass


@dataclass
class aK:
    pass


def run(U, cwd=None, check=True, timeout=60):
    try:
        d = subprocess.run(
            list(U), cwd=str(cwd) if cwd else None, capture_output=True, text=True, check=False, timeout=timeout
        )
    except FileNotFoundError as f:
        raise RuntimeError(f"command not found: {U[0]}") from f
    except subprocess.TimeoutExpired as f:
        raise RuntimeError(f"command timed out: {' '.join(U)}") from f
    if check and d.returncode != 0:
        v = (d.stderr or d.stdout or "").strip() or f"command failed: {' '.join(U)}"
        raise RuntimeError(v)
    return d


def o(c, cwd=None, check=True, timeout=60):
    return run(["git", *c], cwd, check, timeout).stdout


def am(path):
    return (path / ".git").is_dir()


def W(u):
    H = []
    for ag, bm, T in os.walk(u):
        a = Path(ag)
        if (a / ".git").is_dir():
            H.append(a)
            bm[:] = []
    return H


def C(repo):
    j = o(["branch", "--show-current"], repo, check=False).strip()
    if j:
        return j
    j = o(["rev-parse", "--abbrev-ref", "HEAD"], repo).strip()
    if j == "HEAD":
        raise RuntimeError("detached HEAD")
    return j


def bk(repo):
    d = run(["git", "remote", "show", "origin"], repo, check=False)
    if d.returncode == 0:
        for line in d.stdout.splitlines():
            if "HEAD branch" in line:
                return line.split(":", 1)[1].strip()
    ac = o(["branch", "-l"], repo).splitlines()
    bt = [J.strip().replace("*", "").strip() for J in ac if J.strip()]
    for name in ("main", "master"):
        if name in bt:
            return name
    return "main"


def ao(env_file=None):
    l = os.environ.get("GITHUB_TOKEN", "").strip()
    if l:
        return l
    path = (env_file or Path.home() / ".env").expanduser()
    if not path.exists():
        raise RuntimeError(f"GITHUB_TOKEN not found and {path} does not exist")
    for line in path.read_text(encoding="utf-8").splitlines():
        z = line.strip()
        if not z or z.startswith("#"):
            continue
        if z.startswith("export "):
            z = z[7:].lstrip()
        if z.startswith("GITHUB_TOKEN="):
            aJ = z.split("=", 1)[1].strip().strip("\"'")
            if aJ:
                return aJ
    raise RuntimeError(f"GITHUB_TOKEN not found in {path}")


def aj(l, method, g, G=None):
    data = json.dumps(G).encode() if G is not None else None
    O = request.Request(g, data=data, method=method)
    O.add_header("Authorization", f"token {l}")
    O.add_header("Accept", "application/vnd.github.v3+json")
    O.add_header("User-Agent", "git-helper/1.0")
    if G is not None:
        O.add_header("Content-Type", "application/json")
    try:
        with request.urlopen(O, timeout=30) as bA:
            B = bA.read().decode()
            return json.loads(B) if B else {}
    except error.HTTPError as f:
        B = f.read().decode()
        try:
            aD = json.loads(B)
        except Exception:
            aD = {"message": B}
        raise RuntimeError(f"GitHub API {f.code}: {aD.get('message', B)}") from f


def af(l, name, private, description, auto_init):
    G = {"name": name, "private": private, "auto_init": auto_init}
    if description:
        G["description"] = description
    try:
        return aj(l, "POST", "https://api.github.com/user/repos", G)
    except RuntimeError as f:
        if "422" in str(f):
            R = aj(l, "GET", "https://api.github.com/user")["login"]
            return {
                "clone_url": f"https://github.com/{R}/{name}.git",
                "ssh_url": f"git@github.com:{R}/{name}.git",
                "html_url": f"https://github.com/{R}/{name}",
            }
        raise


def bE(g):
    bw = [
        "^git@github\\.com:([^/]+)/(.+?)(?:\\.git)?/?$",
        "^https?://(?:[^@/]+@)?github\\.com/([^/]+)/(.+?)(?:\\.git)?/?$",
    ]
    for bv in bw:
        ap = re.match(bv, g)
        if ap:
            return (ap.group(1), ap.group(2))
    return None


def ah(repo, g, remote="origin"):
    d = run(["git", "remote", "get-url", remote], repo, check=False)
    if d.returncode == 0:
        if d.stdout.strip() != g:
            run(["git", "remote", "set-url", remote, g], repo)
    else:
        run(["git", "remote", "add", remote, g], repo)


def av(repo, message):
    run(["git", "add", "-A"], repo)
    d = run(["git", "status", "--porcelain"], repo)
    if not d.stdout.strip():
        return False
    run(["git", "commit", "-m", message], repo)
    return True


def ar(repo, branch, remote="origin", bp=False):
    c = ["git", "push", "-u", remote, branch]
    if bp:
        c.insert(2, "--force-with-lease")
    run(c, repo)


def aw(repo, aH):
    bo = "%an%x00%ae%x00%ad%x00%s"
    j = o(["show", "-s", f"--format={bo}", aH], repo).strip()
    aS, bn, bj, bD = j.split("\x00")
    return aL(aH, aS, bn, bj, bD)


def bl(repo, F, E):
    bs = o(["diff", "--name-status", F, E], repo).splitlines()
    bu = o(["diff", "--numstat", F, E], repo).splitlines()
    aI = {}
    for line in bu:
        k = line.split("\t")
        if len(k) == 3:
            X, V, path = k
            aI[path] = (None if X == "-" else int(X), None if V == "-" else int(V))
    au = []
    for line in bs:
        k = line.split("\t")
        if not k:
            continue
        A = k[0]
        aC = None
        if A.startswith(("R", "C")) and len(k) == 3:
            aC, path = (k[1], k[2])
        elif len(k) > 1:
            path = k[1]
        else:
            continue
        X, V = aI.get(path, (None, None))
        au.append(aN(A, path, aC, X, V))
    return au


def aX(c):
    repo = Path(c.repo).resolve()
    ak = o(["log", "-2", "--format=%H"], repo).strip().splitlines()
    if len(ak) < 2:
        raise RuntimeError("Repository needs at least 2 commits to diff.")
    E, F = (ak[0], ak[1])
    bz = aM(str(repo), aw(repo, F), aw(repo, E), bl(repo, F, E), o(["diff", F, E], repo))
    j = Path(c.output)
    j.write_text(json.dumps(asdict(bz), indent=2), encoding="utf-8")
    print(f"Wrote diff report: {j}")
    return 0


def bb(c):
    repo = Path(c.repo).resolve()
    ag = C(repo)
    branch = c.branch
    d = run(["git", "cherry", "-v", ag, branch], repo)
    aa = []
    for line in d.stdout.splitlines():
        k = line.split(" ")
        if len(k) > 2:
            aa.append(" ".join(k[2:]))
    reviewer = c.reviewer or f"{input('Reviewer name: ')}<{input('Reviewer email: ')}>"
    message = "\n".join(aa) + f"\n\nReviewed By: {reviewer}"
    run(["git", "merge", "--squash", "--no-log", branch], repo)
    run(["git", "commit", "-m", message], repo)
    print("Successfully merged!")
    return 0


def bC(path):
    try:
        d = run(["git", "status", "--porcelain"], path, check=False, timeout=10)
        if d.returncode != 0:
            return S(path, False, f"Git error: {d.stderr.strip()}")
        Y = [line for line in d.stdout.splitlines() if line.strip()]
        if not Y:
            return S(path, False, "Clean")
        detail = ", ".join(Y[:5])
        if len(Y) > 5:
            detail += f" (+{len(Y) - 5} more)"
        return S(path, True, detail)
    except Exception as f:
        return S(path, False, f"Error: {f}")


def bh(c):
    u = Path(c.path).resolve()
    w = W(u)
    if not w:
        print("No git repositories found.")
        return 0
    with ProcessPoolExecutor(max_workers=c.jobs or None) as y:
        t = list(y.map(bC, w))
    dirty = [e for e in t if e.dirty]
    for e in t:
        if e.dirty:
            print(f"✗ {e.path.name}: CHANGES DETECTED")
            print(f"  └─ {e.detail}")
        else:
            print(f"✓ {e.path.name}: No changes")
            if e.detail != "Clean":
                print(f"  └─ {e.detail}")
    if dirty:
        print(f"Found {len(dirty)} repository(ies) with changes")
    else:
        print("All repositories are clean")
    return 0


def by(repo):
    try:
        branch = C(repo)
        d = run(["git", "remote"], repo, check=False)
        if d.returncode != 0 or not d.stdout.strip():
            return (repo, False, "No remote configured")
        remote = d.stdout.splitlines()[0]
        run(["git", "pull", remote, branch], repo, timeout=120)
        return (repo, True, "Pulled successfully")
    except Exception as f:
        return (repo, False, str(f))


def bd(c):
    u = Path(c.path).resolve()
    w = W(u)
    if not w:
        print("No git repositories found.")
        return 0
    with ProcessPoolExecutor(max_workers=c.jobs or None) as y:
        t = list(y.map(by, w))
    N = [e for e in t if e[1]]
    ab = [e for e in t if not e[1]]
    for repo, T, v in N:
        print(f"✅ {repo.relative_to(u)}: {v}")
    for repo, T, v in ab:
        print(f"❌ {repo.relative_to(u)}: {v}")
    return 0


def bx(repo, l):
    try:
        aF = run(["git", "remote"], repo, check=False).stdout.strip()
        if aF:
            branch = C(repo)
            remote = aF.splitlines()[0]
            run(["git", "pull", remote, branch], repo, timeout=120)
            return (repo, True, "Pulled successfully")
        x = af(l, repo.name, False, f"Repository for {repo.name}", False)
        g = x.get("clone_url") or x.get("ssh_url")
        if not g:
            return (repo, False, "Could not determine remote URL")
        ah(repo, g)
        branch = C(repo)
        ar(repo, branch)
        return (repo, True, f"Created and pushed to {g}")
    except Exception as f:
        return (repo, False, str(f))


def be(c):
    l = ao(Path(c.env_file) if c.env_file else None)
    u = Path(c.path).resolve()
    w = W(u)
    if not w:
        print("No git repositories found.")
        return 0
    with ProcessPoolExecutor(max_workers=c.jobs or None) as y:
        t = list(y.map(bx, w, [l] * len(w)))
    N = [e for e in t if e[1]]
    ab = [e for e in t if not e[1]]
    for repo, T, v in N:
        print(f"✅ {repo.relative_to(u)}: {v}")
    for repo, T, v in ab:
        print(f"❌ {repo.relative_to(u)}: {v}")
    return 0


def aW(c):
    l = ao(Path(c.env_file) if c.env_file else None)
    source = Path(c.source).resolve()
    name = c.name or source.name
    x = af(l, name, c.private, c.description, c.auto_init)
    g = x.get("clone_url") if c.protocol == "https" else x.get("ssh_url")
    if not g:
        raise RuntimeError("Could not determine remote URL")
    if c.push:
        os.chdir(source)
        if not am(source):
            run(["git", "init"], source)
        if c.git_user:
            run(["git", "config", "user.name", c.git_user], source)
        if c.git_email:
            run(["git", "config", "user.email", c.git_email], source)
        av(source, c.commit_message)
        if c.rename_branch:
            run(["git", "branch", "-M", c.branch], source)
        ah(source, g, c.remote)
        ar(source, c.branch, c.remote)
    print(x.get("html_url", g))
    return 0


def bi(c):
    repo = Path(c.repo).resolve()
    n = c.n
    if n <= 0:
        raise RuntimeError("N must be > 0")
    run(["git", "add", "-A"], repo)
    d = run(["git", "status", "--porcelain"], repo)
    if d.stdout.strip():
        run(["git", "commit", "-m", "auto-commit before squash", "--no-verify"], repo)
    al = o(["rev-parse", "HEAD"], repo).strip()
    ax = o(["rev-list", f"--max-count={n}", "--reverse", "HEAD"], repo).splitlines()
    if len(ax) < n:
        raise RuntimeError(f"Repository has fewer than {n} commits")
    K = o(["rev-parse", f"HEAD~{n}"], repo).strip()
    aq = Path(c.patch_file).resolve()
    br = Path(c.meta_file).resolve()
    L = run(["git", "diff", "--binary", f"{K}..{al}"], repo).stdout
    aq.write_text(L, encoding="utf-8")
    br.write_text(json.dumps({"base": K, "head": al, "commits": ax}, indent=2), encoding="utf-8")
    if c.dry_run:
        print(f"Would reset to {K}, apply {aq}, and commit")
        return 0
    run(["git", "reset", "--hard", K], repo)
    run(["git", "apply", "--index", str(aq)], repo)
    run(["git", "add", "-A"], repo)
    aa = o(["log", "--format=%h-%s", f"{K}..{al}"], repo).strip().splitlines()
    message = f"Squash {n} commits: " + "; ".join(aa)
    run(["git", "commit", "-m", message], repo)
    print("Done")
    return 0


def aY(c):
    repo = Path(c.repo).resolve()
    run(["git", "fetch", "origin"], repo)
    at = None
    for aE in ("origin/master", "origin/main"):
        d = run(["git", "rev-parse", "--verify", aE], repo, check=False)
        if d.returncode == 0:
            at = aE
            break
    if not at:
        raise RuntimeError("Neither origin/master nor origin/main exists")
    branch = C(repo)
    d = run(["git", "rebase", "--onto", at, "HEAD", branch], repo, check=False)
    if d.returncode != 0:
        run(["git", "rebase", "--abort"], repo, check=False)
        raise RuntimeError(d.stderr.strip() or "Rebase failed")
    run(["git", "push", "--force-with-lease", "origin", branch], repo)
    print("Successfully synced branch")
    return 0


def aZ(c):
    line = c.line.strip()
    if not line:
        raise RuntimeError("line cannot be empty")
    paths = [Path(a).resolve() for a in c.paths or ["."]]
    ai = []
    for path in paths:
        if path.is_file() and path.name == ".gitignore":
            ai.append(path)
        elif path.is_dir():
            ai.extend((a for a in path.rglob(".gitignore") if a.is_file()))
    M = 0
    for path in ai:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            if line in text.splitlines():
                continue
            if text and (not text.endswith("\n")):
                text += "\n"
            text += line + "\n"
            path.write_text(text, encoding="utf-8")
            M += 1
            print(f"Updated {path}")
        except Exception as f:
            print(f"Failed {path}: {f}", file=sys.stderr)
    print(f"Modified {M} file(s)")
    return 0


def ba(c):
    repo = Path(c.repo).resolve()
    if not am(repo):
        raise RuntimeError("Not a git repository")
    D = bk(repo)
    ac = [J.strip().replace("*", "").strip() for J in o(["branch", "-l"], repo).splitlines() if J.strip()]
    for branch in ac:
        if branch != D:
            run(["git", "branch", "-D", branch], repo, check=False)
    run(["git", "checkout", D], repo)
    run(["git", "checkout", "--orphan", "temp_branch"], repo)
    run(["git", "add", "-A"], repo)
    run(["git", "commit", "-m", "Squashed history, keeping last commit"], repo)
    run(["git", "branch", "-D", D], repo)
    run(["git", "branch", "-m", D], repo)
    print("Cleanup completed")
    return 0


def bB(repo):
    try:
        run(["git", "restore", "."], repo)
        return (repo, True, "Restored")
    except Exception as f:
        return (repo, False, str(f))


def bg(c):
    u = Path(c.path).resolve()
    w = W(u)
    if not w:
        print("No git repositories found.")
        return 0
    with ProcessPoolExecutor(max_workers=c.jobs or None) as y:
        t = list(y.map(bB, w))
    for repo, N, v in t:
        bq = "✅" if N else "❌"
        print(f"{bq} {repo.relative_to(u)}: {v}")
    return 0


def aU(c):
    repo = Path(c.repo).resolve()
    P = o(["rev-list", c.branch], repo).splitlines()
    if c.max_count:
        P = P[: c.max_count]
    t = []
    for Q in P:
        d = run(["git", "show", "-s", "--format=%H%x1f%an%x1f%ae%x1f%aI%x1f%s", Q], repo)
        k = d.stdout.strip().split("\x1f")
        if len(k) < 5:
            continue
        az, aQ, aP, aO, v = k
        L = run(["git", "diff-tree", "--no-commit-id", "--name-status", "-r", "-M", "--root", Q], repo).stdout
        I = []
        M = []
        ay = []
        aG = []
        for line in L.splitlines():
            i = line.split("\t")
            if not i:
                continue
            A = i[0]
            if A.startswith("A") and len(i) > 1:
                I.append(i[1])
            elif A.startswith("M") and len(i) > 1:
                M.append(i[1])
            elif A.startswith("D") and len(i) > 1:
                ay.append(i[1])
            elif A.startswith(("R", "C")) and len(i) > 2:
                aG.append({"from": i[1], "to": i[2]})
        t.append(aK(az, az[:8], aQ, aP, aO, v, I, M, ay, aG))
    j = Path(c.output)
    j.write_text(json.dumps([asdict(e) for e in t], indent=2), encoding="utf-8")
    print(f"Wrote {len(t)} commits to {j}")
    return 0


def bf(c):
    repo = Path(c.repo).resolve()
    P = o(["rev-list", "HEAD"], repo).splitlines()
    H = {}
    for Q in P:
        L = run(["git", "diff-tree", "--no-commit-id", "--name-status", "-r", "-M", "--root", Q], repo).stdout
        I = []
        for line in L.splitlines():
            i = line.split("\t")
            if i and i[0].startswith("A") and (len(i) > 1):
                I.append(Path(i[1]).name)
        H[Q[:8]] = sorted(set(I))
    j = Path(c.output)
    j.write_text(json.dumps(H, indent=2), encoding="utf-8")
    print(f"Wrote {len(H)} commits to {j}")
    return 0


def aV(c):
    repo = Path(c.repo).resolve()
    aA = Path.home() / ".gitignore"
    aB = repo / ".gitignore"
    if aA.exists() and (not aB.exists()):
        shutil.copy2(aA, aB)
    run(["git", "add", "-A"], repo)
    message = datetime.now().strftime("Auto-commit at %Y-%m-%d %H:%M:%S")
    d = run(["git", "status", "--porcelain"], repo)
    if d.stdout.strip():
        run(["git", "commit", "-m", message], repo)
    branch = C(repo)
    run(["git", "push", "origin", branch], repo)
    print(f"Pushed to origin/{branch} with message: {message}")
    return 0


def bc(c):
    l = ao(Path(c.env_file) if c.env_file else None)
    repo = Path.cwd().resolve()
    name = c.name or repo.name
    R = aj(l, "GET", "https://api.github.com/user")["login"]
    x = af(l, name, c.private, c.description, False)
    g = x.get("clone_url") or x.get("ssh_url")
    if not g:
        raise RuntimeError("Could not determine remote URL")
    if not am(repo):
        run(["git", "init", "-b", c.branch], repo)
    if not (repo / ".gitignore").exists() and (Path.home() / ".gitignore").exists():
        shutil.copy2(Path.home() / ".gitignore", repo / ".gitignore")
    av(repo, c.message)
    run(["git", "branch", "-M", c.branch], repo)
    ah(repo, g)
    ar(repo, c.branch)
    print(f"https://github.com/{R}/{name}")
    return 0


def aT():
    Z = argparse.ArgumentParser(prog="git-helper")
    q = Z.add_subparsers(dest="command", required=True)
    a = q.add_parser("diff-report")
    a.add_argument("repo", nargs="?", default=".")
    a.add_argument("output", nargs="?", default="diff_report.json")
    a.set_defaults(func=aX)
    a = q.add_parser("merge-squash")
    a.add_argument("branch")
    a.add_argument("--repo", default=".")
    a.add_argument("--reviewer")
    a.set_defaults(func=bb)
    a = q.add_parser("scan-changes")
    a.add_argument("path", nargs="?", default=".")
    a.add_argument("--jobs", type=int)
    a.set_defaults(func=bh)
    a = q.add_parser("pull-all")
    a.add_argument("path", nargs="?", default=".")
    a.add_argument("--jobs", type=int)
    a.set_defaults(func=bd)
    a = q.add_parser("pull-new")
    a.add_argument("path", nargs="?", default=".")
    a.add_argument("--env-file")
    a.add_argument("--jobs", type=int)
    a.set_defaults(func=be)
    a = q.add_parser("create-repo")
    a.add_argument("--name")
    a.add_argument("--source", default=".")
    a.add_argument("--description")
    a.add_argument("--private", action="store_true")
    a.add_argument("--auto-init", action="store_true")
    a.add_argument("--push", action="store_true")
    a.add_argument("--env-file")
    a.add_argument("--remote", default="origin")
    a.add_argument("--protocol", choices=["https", "ssh"], default="ssh")
    a.add_argument("--branch", default="main")
    a.add_argument("--commit-message", default="Update files")
    a.add_argument("--git-user")
    a.add_argument("--git-email")
    a.add_argument("--rename-branch", action="store_true")
    a.set_defaults(func=aW)
    a = q.add_parser("squash")
    a.add_argument("n", type=int)
    a.add_argument("--repo", default=".")
    a.add_argument("--patch-file", default="saved_patch.diff")
    a.add_argument("--meta-file", default="saved_patch.meta.json")
    a.add_argument("--dry-run", action="store_true")
    a.set_defaults(func=bi)
    a = q.add_parser("fix")
    a.add_argument("repo", nargs="?", default=".")
    a.set_defaults(func=aY)
    a = q.add_parser("gitignore-add")
    a.add_argument("line")
    a.add_argument("paths", nargs="*")
    a.set_defaults(func=aZ)
    a = q.add_parser("keep-main")
    a.add_argument("repo", nargs="?", default=".")
    a.set_defaults(func=ba)
    a = q.add_parser("restore")
    a.add_argument("path", nargs="?", default=".")
    a.add_argument("--jobs", type=int)
    a.set_defaults(func=bg)
    a = q.add_parser("added-files")
    a.add_argument("repo", nargs="?", default=".")
    a.add_argument("output", nargs="?", default="added_files.json")
    a.add_argument("--branch", default="HEAD")
    a.add_argument("--max-count", type=int)
    a.set_defaults(func=aU)
    a = q.add_parser("report")
    a.add_argument("repo", nargs="?", default=".")
    a.add_argument("output", nargs="?", default="added_files.json")
    a.set_defaults(func=bf)
    a = q.add_parser("auto-commit-push")
    a.add_argument("repo", nargs="?", default=".")
    a.set_defaults(func=aV)
    a = q.add_parser("newrepo")
    a.add_argument("--name")
    a.add_argument("--private", action="store_true")
    a.add_argument("--description")
    a.add_argument("--message", default="Initial commit")
    a.add_argument("--branch", default="main")
    a.add_argument("--env-file")
    a.set_defaults(func=bc)
    return Z


def D(aR=None):
    Z = aT()
    c = Z.parse_args(aR)
    try:
        return int(c.func(c))
    except Exception as f:
        print(f"Error: {f}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(D())
