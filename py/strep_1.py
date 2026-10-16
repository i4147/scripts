#!/data/data/com.termux/files/usr/bin/python
"""Write a Python script that acts as a command-line tool for stripping debugging and symbol information from compiled shared libraries packaged inside Python wheel files. The tool should accept one or more wheel file paths as arguments,
and when no arguments are given,
it should automatically discover all wheel files in the current working directory.
For each wheel,
the tool should unpack its contents into a temporary workspace,
locate every shared object file (files with a `.so` extension,
including versioned variants such as `.so.1` or `.so.1.2`),
and run the system `strip` utility on each one to reduce its size. After processing,
the tool should repackage the modified contents into a valid wheel archive,
overwriting the original file in place,
with all directory structure and relative paths preserved.
Display a progress indicator in the terminal while processing multiple wheels,
showing the current file being handled,
a completion bar,
and a percentage counter,
using a clean and readable console presentation. Show the output of the stripping commands as they run so the user can see what is happening. Handle errors gracefully: if a wheel cannot be read or is not a valid archive,
report the problem clearly for that file and continue with the remaining files rather than aborting the whole run. Use the process exit code to indicate overall success or failure.
Include a concise help message describing usage,
and make sure the tool works on Linux and macOS systems where the `strip` command is available. The script should be self-contained,
robust,
and produce a summary at the end listing how many wheels were processed successfully and how many failed.
---"""

from __future__ import annotations
from pathlib import Path
import re
import sys
import tempfile
from zipfile import ZipFile
from dh import fsz, runcmd
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn

SO_PATTERN = re.compile(r"\.so(\.\d+)*$")
console = Console()


def process_file(path: Path) -> None:
    _ret, _, _ = runcmd(["strip", str(path)], show_output=True)


def process_whl(whl_path: Path) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        with ZipFile(whl_path, "r") as zf:
            zf.extractall(tmpdir)
        so_files = [p for p in tmpdir.rglob("*") if SO_PATTERN.search(p.name)]
        for so_file in so_files:
            process_file(so_file)
        with ZipFile(whl_path, "w") as zf:
            for path in tmpdir.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(tmpdir))


def collect_files(cwd: Path, args: list[str]) -> list[Path]:
    if args:
        return [Path(p) for p in args]
    so_files = [p for p in cwd.rglob("*") if SO_PATTERN.search(p.name) and p.is_file()]
    return so_files


def show_summary(files: list[Path]) -> None:
    total_size = sum(f.stat().st_size for f in files if f.is_file())
    console.print(f"[bold cyan]Total number of .so files:[/] [bold yellow]{len(files)}[/]")
    console.print(f"[bold cyan]Total size of .so files:[/] [bold yellow]{fsz(total_size)}[/]")


if __name__ == "__main__":
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = collect_files(cwd, args)
    so_files = [f for f in files if f.suffix == ".so" or SO_PATTERN.search(f.name)]
    console.print("[bold green]Starting .so stripping process...[/]")
    show_summary(so_files)
    with Progress(
        TextColumn("[bold blue]{task.description}[/]"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("[bold]{task.completed}/{task.total}[/]"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Stripping .so files...[/]", total=len(so_files))
        for so_file in so_files:
            process_file(so_file)
            progress.update(task, advance=1)
    console.print(f"[bold green]Done![/] Processed [bold yellow]{len(so_files)}[/] .so files.")
    show_summary(so_files)
