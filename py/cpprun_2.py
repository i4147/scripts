"""
Termux-friendly C / C++ runner.
Usage: cpprun file.c | file.cpp | file.cc
"""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path


# Map extension -> (preferred compiler, fallbacks)
COMPILERS = {
    ".c": ("clang", ("clang", "gcc")),
    ".cpp": ("clang++", ("clang++", "g++")),
    ".cc": ("clang++", ("clang++", "g++")),
    ".cxx": ("clang++", ("clang++", "g++")),  # bonus
}


def _pick_compiler(candidates):
    for c in candidates:
        if shutil.which(c):
            return c
    return None


def cpp_run(*args):
    if not args:
        print("Usage: cpprun <file.c|file.cpp|file.cc>")
        return 1

    src = Path(args[0]).expanduser().resolve()
    if not src.is_file():
        print(f"Error: {src} not found", file=sys.stderr)
        return 1

    ext = src.suffix.lower()
    if ext not in COMPILERS:
        print(f"Error: unsupported extension '{ext}'. Expected one of: {', '.join(COMPILERS)}", file=sys.stderr)
        return 1

    preferred, fallbacks = COMPILERS[ext]
    compiler = _pick_compiler((preferred, *fallbacks))
    if compiler is None:
        print(f"Error: no compiler for {ext} found. Run: pkg install clang", file=sys.stderr)
        return 1

    # Put the binary somewhere Android allows execution.
    tmpdir = Path(
        os.environ.get("TMPDIR") or f"{os.environ.get('PREFIX', '/data/data/com.termux/files/usr')}/tmp" or Path.home()
    )
    tmpdir.mkdir(parents=True, exist_ok=True)
    exe = tmpdir / src.stem

    # Compile — C uses -std=c17, C++ uses -std=c++17.
    std_flag = "-std=c17" if ext == ".c" else "-std=c++17"
    cmd = [compiler, std_flag, "-Wall", "-Wextra", "-O2", str(src), "-o", str(exe)]

    if subprocess.run(cmd).returncode != 0:
        return 1

    # Ensure it's executable (some Android FS quirks).
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # Run with absolute path (Termux PATH doesn't include ".").
    try:
        return subprocess.run([str(exe), *args[1:]]).returncode
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(cpp_run(*sys.argv[1:]))
