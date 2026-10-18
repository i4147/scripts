#!/data/data/com.termux/files/usr/bin/python
"""Write a Python script that analyzes a local Git repository and reports, for each commit, which files were newly added in that commit. The tool should accept the path to a repository as input and produce a structured result mapping each commit identifier to the list of files that first appeared in that commit, including files whose paths were introduced by the commit relative to its parent state. It should handle commits with no parents (initial commits) by treating all files in their tree as added, and it should skip or gracefully handle merge commits and deleted or renamed files so that only genuinely new paths are reported. The script should traverse the full commit history reachable from the repository's current branch, avoid redundant work by reusing previously computed file listings for identical tree states, and support both human-readable console output and machine-readable JSON output selected through a command-line option. It should validate that the provided path is a valid repository and report clear error messages for invalid paths, empty repositories, or repositories with unreadable objects. The output should preserve commit order from oldest to newest and include the commit hash, author name, commit timestamp, and the sorted list of added file paths for each commit.
---"""

from __future__ import annotations
import argparse
import json
import subprocess
import pygit2
from dulwich.repo import Repo
from git import Repo as GitRepo


def get_added_files_per_commit_dulwich(repo_path: str) -> dict:
    repo = Repo(repo_path)
    result = {}
    try:
        walker = repo.get_walker()
        commits = list(walker)
        tree_files_cache = {}

        def tree_files(tree_sha):
            if tree_sha in tree_files_cache:
                return tree_files_cache[tree_sha]
            files = set()
            tree = repo[tree_sha]
            stack = [("", tree)]
            while stack:
                prefix, t = stack.pop()
                for item in t.iteritems():
                    name = item.path.decode() if isinstance(item.path, bytes) else item.path
                    full = f"{prefix}{name}"
                    if item.mode & 0o170000 == 0o040000:
                        stack.append((full + "/", repo[item.sha]))
                    else:
                        files.add(full)
            tree_files_cache[tree_sha] = files
            return files

        for entry in commits:
            commit = entry.commit
            commit_sha = commit.id.decode()
            short = commit_sha[:8]
            current_files = tree_files(commit.tree)
            parent_files = set()
            for parent_sha in commit.parents:
                parent = repo[parent_sha]
                parent_files |= tree_files(parent.tree)
            added = current_files - parent_files
            added_names = sorted({f.split("/")[-1] for f in added})
            result[short] = added_names
    finally:
        repo.close()
    return result


def get_added_files_per_commit_pygit2(repo_path: str) -> dict:
    repo = pygit2.Repository(repo_path)
    result = {}
    tree_files_cache = {}

    def tree_files(tree_id: str) -> set:
        if tree_id in tree_files_cache:
            return tree_files_cache[tree_id]
        files = set()
        tree = repo[tree_id]
        stack = [("", tree)]
        while stack:
            prefix, t = stack.pop()
            for entry in t:
                name = entry.name
                full = f"{prefix}{name}"
                if entry.filemode == pygit2.GIT_FILEMODE_TREE:
                    stack.append((full + "/", repo[entry.id]))
                else:
                    files.add(full)
        tree_files_cache[tree_id] = files
        return files

    head = repo.revparse_single("HEAD")
    for commit in repo.walk(head.id, pygit2.GIT_SORT_TIME):
        commit_sha = str(commit.id)
        short = commit_sha[:8]
        current_files = tree_files(str(commit.tree_id))
        parent_files = set()
        for parent in commit.parents:
            parent_files |= tree_files(str(parent.tree_id))
        added = current_files - parent_files
        added_names = sorted({f.split("/")[-1] for f in added})
        result[short] = added_names
    return result


def get_added_files_per_commit_gitpython(repo_path: str) -> dict:
    repo = GitRepo(repo_path)
    result = {}
    tree_files_cache = {}

    def tree_files(tree) -> set:
        key = tree.hexsha
        if key in tree_files_cache:
            return tree_files_cache[key]
        files = set()
        stack = [("", tree)]
        while stack:
            prefix, t = stack.pop()
            for item in t:
                name = item.name
                full = f"{prefix}{name}"
                if item.type == "tree":
                    stack.append((full + "/", item))
                else:
                    files.add(full)
        tree_files_cache[key] = files
        return files

    for commit in repo.iter_commits("HEAD"):
        short = commit.hexsha[:8]
        current_files = tree_files(commit.tree)
        parent_files = set()
        for parent in commit.parents:
            parent_files |= tree_files(parent.tree)
        added = current_files - parent_files
        added_names = sorted({f.split("/")[-1] for f in added})
        result[short] = added_names
    return result


def get_added_files_per_commit_gitcli(repo_path: str) -> dict:
    result = {}
    tree_files_cache = {}

    def tree_files(tree_sha: str) -> set:
        if tree_sha in tree_files_cache:
            return tree_files_cache[tree_sha]
        out = subprocess.run(
            ["git", "-C", repo_path, "ls-tree", "-r", "--name-only", tree_sha],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        files = {line for line in out.splitlines() if line}
        tree_files_cache[tree_sha] = files
        return files

    log = subprocess.run(
        ["git", "-C", repo_path, "log", "--format=%H %T %P"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    for line in log.splitlines():
        parts = line.split()
        if not parts:
            continue
        commit_sha = parts[0]
        tree_sha = parts[1]
        parents = parts[2:]
        short = commit_sha[:8]
        current_files = tree_files(tree_sha)
        parent_files = set()
        for parent_sha in parents:
            parent_tree = subprocess.run(
                ["git", "-C", repo_path, "rev-parse", f"{parent_sha}^{{tree}}"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            parent_files |= tree_files(parent_tree)
        added = current_files - parent_files
        added_names = sorted({f.split("/")[-1] for f in added})
        result[short] = added_names
    return result


BACKENDS = {
    "dulwich": get_added_files_per_commit_dulwich,
    "pygit2": get_added_files_per_commit_pygit2,
    "gitpython": get_added_files_per_commit_gitpython,
    "gitcli": get_added_files_per_commit_gitcli,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_path", nargs="?", default=".")
    parser.add_argument("output_path", nargs="?", default="added_files.json")
    parser.add_argument("-b", "--backend", choices=list(BACKENDS), default="dulwich")
    args = parser.parse_args()
    data = BACKENDS[args.backend](args.repo_path)
    with open(args.output_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Wrote {len(data)} commits to {args.output_path} using {args.backend}")


if __name__ == "__main__":
    main()
