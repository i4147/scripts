import subprocess
import sys
from pathlib import Path

TERMUX_PYTHON = "#!/data/data/com.termux/files/usr/bin/python\n"
TERMUX_BASH = "#!/data/data/com.termux/files/usr/bin/bash\n"
cwd = Path.cwd()
homebin = Path.home() / "bin"
homebin2 = Path.home() / "bashbin"


def get_clipboard() -> str:
    try:
        return subprocess.check_output(["termux-clipboard-get"], text=True)
    except subprocess.CalledProcessError:
        sys.exit(1)


def detect_shebang(content: str) -> str | None:
    stripped = content.lstrip()
    if stripped.startswith("#!") and "python" in stripped[5:200]:
        return TERMUX_PYTHON
    if stripped.startswith(("import ", "def ", "class ", "!python", "from ")):
        return TERMUX_PYTHON
    if stripped.startswith(("echo ", "cd ", "export ", "set ", "if ", "for ", "#!/bin/sh")):
        return TERMUX_BASH
    return None


def create_symlink(out_file: Path) -> None:
    ext = out_file.suffix
    if ext and cwd in {homebin, homebin2}:
        symlink_path = out_file.parent / out_file.stem
        if not symlink_path.exists():
            symlink_path.symlink_to(out_file)
            print(f"{symlink_path} -> {out_file}")
        else:
            print("symlink exists.")


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(1)
    out_file = Path(sys.argv[1])
    content = get_clipboard()
    if not content:
        content = "\n"
    if cwd in {homebin, homebin2}:
        shebang = detect_shebang(content)
        if shebang:
            content = shebang + content
    lines = content.splitlines()
    if lines[0].startswith("#!") and lines[1].startswith("#!"):
        lines.pop(1)
        content = "\n".join(lines)
    out_file.write_text(content, encoding="utf-8")
    if cwd in {homebin, homebin2}:
        out_file.chmod(493)
        create_symlink(out_file)


if __name__ == "__main__":
    main()
