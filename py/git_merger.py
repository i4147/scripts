#!/data/data/com.termux/files/usr/bin/python
"""Write a Python script that acts as an interactive command-line tool for managing branches in a Git repository. The tool should be run from within a Git repository directory; if it is not, it should print a clear message and exit gracefully.
Core behavior:
- Detect the current repository and verify that the user is inside a valid Git working copy before doing anything else.
- Present the user with a set of branch-management operations, such as listing local branches (excluding the currently active branch), switching to another branch, creating new branches, deleting branches, and cleaning up merged or stale branches.
- Provide interactive terminal dialogs for the user: confirmation prompts (yes/no) before any destructive action, single-choice selection lists for picking a branch, and multi-select checklists for bulk operations.
- Offer branch name autocompletion when the user is typing a branch name on the command line, so that partial input suggests matching existing branches.
- Support a command-line interface with subcommands and options, so the same operations can be run non-interactively from the shell as well as through the interactive menu.
- Protect the user from mistakes: never delete the currently checked-out branch, warn about unmerged or unpushed work before removing a branch, and require explicit confirmation for force operations.
- Display results using color-coded, readable status messages (for example, green for success, yellow for warnings, red for errors), and log significant actions for traceability.
- Handle errors from Git operations gracefully, reporting the problem in plain language instead of crashing with a raw traceback.
- Keep the script self-contained in a single file, with a clear entry point, helpful `--help` output, and sensible defaults.
Inputs: the current working directory (must be a Git repository), the user's menu selections and dialog responses, and command-line arguments and options.
Outputs: changes to the repository's branches (created, switched, renamed, or deleted), colorized console feedback for each action, and log entries recording what was done.
---"""

import os
from pathlib import Path
import click
import colored
import git
from prompt_toolkit import prompt
from prompt_toolkit.shortcuts import button_dialog, checkboxlist_dialog, radiolist_dialog, yes_no_dialog
from sh import git

repo = None
g = None
try:
    repo = git.Repo(".")
    g = git.cmd.Git()
except:
    print("Not in a repo directory!")
    exit()


class RepoManager:
    @staticmethod
    def get_list_branches(ignore_current=True):
        return [branch.name for branch in repo.branches if branch.name != repo.active_branch.name]

    @staticmethod
    def get_autocomplete_list_branches(ctx, args, incomplete):
        return [branch.name for branch in RepoManager.get_list_branches() if incomplete in branch.name]

    @staticmethod
    def ask(title, text):
        return yes_no_dialog(title=title, text=text).run()

    @staticmethod
    def verify_branch():
        return RepoManager.ask(
            "Branch Verification",
            f"Current Branch: {repo.active_branch.name} is this correct?",
        )

    @staticmethod
    def cherry(first, second):
        from sh import git

        cmd = ["cherry", "-v", first, second]
        response = git(cmd).strip().split("\n")
        commits = []
        for commit in response:
            commit = commit.split(" ")
            commits.append(" ".join(commit[2:]))
        return commits

    @staticmethod
    def fetch_synced_remotes():
        refs = repo.refs
        remotes = []
        for ref in refs:
            if isinstance(ref, git.refs.remote.RemoteReference):
                if ref.name not in ["origin/HEAD", "origin/master"]:
                    remotes.append(ref)
        return remotes

    @staticmethod
    def recent_branches(count=os.environ.get("RECENT_COUNT", 5)):
        from sh import git

        cmd = [
            "for-each-ref",
            f"--count={count}",
            "--sort=-committerdate",
            "refs/heads/",
            "--format=%(refname:short)",
        ]
        response = git(cmd)
        return response

    @staticmethod
    def choose_repos_from_list(title, message, items):
        picked = checkboxlist_dialog(
            title=title,
            text=message,
            values=[(x.name, x.name) for x in items],
        ).run()
        selected = []
        if not picked:
            return []
        for item in items:
            for pick in picked:
                if item.name == pick:
                    selected.append(item)
                    break
        return selected


class AuthorManager:
    def __init__(self):
        import json

        self.authors = None
        if os.path.exists("authors.json"):
            with open("authors.json", "r") as f:
                self.authors = json.loads(f.read())
                self.authors = self.authors["authors"]

    def ask(self):
        if self.authors:
            authors = []
            for index, author in enumerate(self.authors):
                name = f"{author['name']} <{author['email']}>"
                authors.append((name, name))
            response = radiolist_dialog(
                title="Reviewer Picker",
                text="Who reviewed this?",
                values=authors,
            ).run()
            if response != None:
                return response
        name = prompt("Whats the reviewers name?: ")
        email = prompt("Whats the reviewers email?: ")
        return f"{name} <{email}>"


class Printer:
    def _default_label_colors(self):
        return colored.fg("white")

    def _default_value_colors(self):
        return colored.fg("white")

    def _generate_label_colors(self, colors):
        if colors:
            return colors
        else:
            return self._default_label_colors()

    def _generate_value_colors(self, colors):
        if colors:
            return colors
        else:
            return self._default_value_colors()

    def autocomplete(self):
        path_folder = os.path.dirname(__file__)
        path = Path(path_folder)
        path_autocomplete = os.path.join(path)
        print(f"""{colored.fg("green")}AUTOCOMPLETE
===============
ZSH:
source {path_autocomplete}/merger-zsh-complete.sh
FISH:
source {path_autocomplete}/merger-fish-complete.sh
BASH:
source {path_autocomplete}/merger-bash-complete.sh
""")

    def banner(self, message="Merger"):
        from pyfiglet import print_figlet

        print_figlet(message, colors="LIGHT_CYAN")

    def merged(
        self,
        label_colors=colored.fg("white") + colored.bg("green"),
        value_colors=colored.fg("white") + colored.bg("green"),
    ):
        label_colors = self._generate_label_colors(label_colors)
        value_colors = self._generate_value_colors(value_colors)
        print(f"{label_colors}Merger: {value_colors} Successfully merged!")

    def branches(
        self,
        label_colors=None,
        value_colors=None,
    ):
        print(f"""{colored.fg("yellow")}Current Branch:\n===============\n{repo.active_branch.name}\n""")
        print(f"""{colored.fg("yellow")}Recent Branches ({os.environ.get("RECENT_COUNT", 5)})\n===============""")
        print(str(RepoManager.recent_branches()) + colored.fg("white"))

    def space(self):
        print("\n")

    def invalid_branch(
        self,
        branch,
        label_colors=colored.fg("white") + colored.bg("red"),
        value_colors=colored.fg("white") + colored.bg("red"),
    ):
        label_colors = self._generate_label_colors(label_colors)
        value_colors = self._generate_value_colors(value_colors)
        print(f"{label_colors}Error: {value_colors} {branch} is not correct! Please try again.")

    def error(
        self,
        label,
        error,
        label_colors=colored.fg("white") + colored.bg("red"),
        value_colors=colored.fg("white") + colored.bg("red"),
    ):
        label_colors = self._generate_label_colors(label_colors)
        value_colors = self._generate_value_colors(value_colors)
        print(f"{label_colors}{label}: {value_colors} {error}")


printer = Printer()


@click.group()
def cli():
    pass


@cli.command()
def help_stats():
    printer.banner()
    printer.branches()


@cli.command()
def help_autocomplete():
    printer.banner()
    printer.autocomplete()


@cli.command()
@click.argument(
    "branch",
    type=click.Choice(RepoManager.get_list_branches()),
    autocompletion=RepoManager.get_list_branches,
)
def merge(branch):
    if RepoManager.verify_branch():
        authorManager = AuthorManager()
        author = authorManager.ask()
        if author is None:
            printer.error("Author", "Not chosen")
            exit()
        commits = "\n".join(RepoManager.cherry(repo.active_branch, branch))
        commit_message = f"""{commits}
Reviewed By: {author}"""
        repo.git.merge("--squash", "--no-log", branch)
        repo.index.commit(commit_message)
        printer.merged()
    else:
        printer.invalid_branch(repo.active_branch.name)


@cli.group(help="Helper functions used for cleaning up")
def clean():
    pass


@clean.command(help="Process to clean up remote branches")
def remote():
    recent_branches = RepoManager.recent_branches(count=999999999)
    remote_branches = RepoManager.fetch_synced_remotes()
    if len(remote_branches) == 0:
        button_dialog(title="ERROR", text="NO REMOTE BRANCHES FOUND", buttons=[("OK", True)]).run()
        exit()
    selected = RepoManager.choose_repos_from_list(
        "BRANCH REMOTE CLEANER",
        "CHOOSE BRANCHES FROM THE LIST BELOW TO DELETE",
        remote_branches,
    )
    if len(selected) == 0:
        print("No branches selected")
        return
    question = RepoManager.ask(
        "ARE YOU SURE?",
        f"ARE YOU SURE YOU WISH TO DELETE THESE BRANCHES?: {', '.join([x.name for x in selected])}",
    )
    if question:
        for x in selected:
            name = x.name.split("/")[1:]
            repo.git.push("origin", "--delete", name)
        button_dialog(title="REMOTES DELETED", buttons=[("OK", True)]).run()
        exit()
    else:
        print("No branches deleted")


@cli.group(help="Development tools")
def tools():
    pass


@tools.command(help="Used to create test branches")
def create_test_branches(names=["1.0.0", "2.0.0", "3.0.0"]):
    origin = repo.remote()
    for x in names:
        branch = repo.create_head(x)
        branch.checkout()
        origin.push(x)
    g.checkout("master")


cli()
