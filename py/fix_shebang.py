#!/usr/bin/env python3

from pathlib import Path
import os
import stat

HOME = Path.home()
cwd = Path.cwd()

# Termux prefix — adjust if you ever change it
PREFIX = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))

# New target for the shebang
NEW_SHEBANG = f"#!{PREFIX}/bin/python3.12"

# Prefixes we consider "old Python" and want to replace.
# Anything whose shebang starts with one of these and mentions python
# will be rewritten.
OLD_PREFIXES = (
    str(HOME / ".local/bin"),
    str(PREFIX / "bin"),
    "/usr/bin",
    "/usr/local/bin",
    "/usr/bin/env",
    "/opt/homebrew/bin",
    "/usr/local/opt",
)


def looks_like_python_interpreter(interp: str) -> bool:
    """True if the interpreter path/command contains 'python'."""
    name = Path(interp).name
    return "python" in name


def should_rewrite(interp: str) -> bool:
    """Decide if we should replace this shebang."""
    if not looks_like_python_interpreter(interp):
        return False

    # If it already points at the new wrapper, skip.
    if interp.strip() == str(PREFIX / "bin/python3.12"):
        return False

    # If it's `python3.12` specifically, we still rewrite to the wrapper
    # so PYTHONHOME/LD_LIBRARY_PATH get set.
    return True


def parse_shebang(first_line: str):
    """
    Return interpreter string (without '#!') or None if not a shebang.
    Handles `#!/usr/bin/env python3` -> 'python3'
    and `#!/path/to/python3.12 -O` -> '/path/to/python3.12 -O'
    """
    if not first_line.startswith("#!"):
        return None
    body = first_line[2:].strip()
    if not body:
        return None

    parts = body.split()
    if not parts:
        return None

    exe = parts[0]
    # Special case: `env pythonX` → interpreter is the second token
    if Path(exe).name == "env" and len(parts) >= 2:
        return parts[1]
    return exe


def rewrite_file(path: Path) -> bool:
    """Rewrite a single file's shebang. Returns True if modified."""
    try:
        data = path.read_bytes()
    except (OSError, PermissionError) as e:
        print(f"  ! cannot read {path}: {e}")
        return False

    # Skip binary files
    if b"\x00" in data[:1024]:
        return False

    # Read first line
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False

    first_newline = text.find("\n")
    if first_newline == -1:
        first_line, rest = text, ""
    else:
        first_line, rest = text[:first_newline], text[first_newline:]

    interp = parse_shebang(first_line)
    if interp is None:
        return False
    if not should_rewrite(interp):
        return False

    new_content = NEW_SHEBANG + rest

    # Preserve mode; write atomically-ish
    try:
        mode = path.stat().st_mode
        tmp = path.with_suffix(path.suffix + ".shebang.tmp")
        tmp.write_text(new_content, encoding="utf-8")
        os.chmod(tmp, stat.S_IMODE(mode))
        tmp.replace(path)
    except OSError as e:
        print(f"  ! cannot write {path}: {e}")
        return False

    print(f"  ✓ {path.name}:  {interp}  →  {PREFIX}/bin/python3.12")
    return True


def main():
    if not cwd.is_dir():
        print(f"Directory not found: {cwd}")
        return

    print(f"Scanning {cwd} …")
    changed = 0
    scanned = 0

    for path in sorted(cwd.iterdir()):
        if not path.is_file():
            continue
        # Only executable files
        if not os.access(path, os.X_OK):
            continue
        scanned += 1
        if rewrite_file(path):
            changed += 1

    print()
    print(f"Scanned {scanned} executable file(s); rewrote {changed} shebang(s).")


if __name__ == "__main__":
    main()
