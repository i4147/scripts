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
        print("Error: failed to get clipboard content", file=sys.stderr)
        sys.exit(1)


def detect_shebang(content: str) -> str | None:
    stripped = content.lstrip()
    if stripped.startswith("#!") and "python" in stripped:
        return "python"
    if "import " in content or "def " in content or "class " in content or stripped.startswith("!python"):
        return "python2"
    if stripped.startswith("#!/bin/sh"):
        return "bash"
    if stripped.startswith(("echo ", "cd ", "export ", "set ", "if ", "for ")):
        return "bash2"
    return None


def create_symlink(out_file: Path) -> None:
    ext = out_file.suffix
    if ext and cwd in {homebin, homebin2}:
        symlink_path = Path(str(out_file.parent) + "/" + out_file.stem)
        try:
            symlink_path.symlink_to(out_file)
            print(f"{symlink_path.name} -> {out_file.name}")
        except FileExistsError:
            print(f"{symlink_path.name} exists.")
        except Exception as e:
            print(f"Error creating symlink: {e}", file=sys.stderr)


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <output-file>", file=sys.stderr)
        sys.exit(1)
    out_file = Path(sys.argv[1])
    content = get_clipboard()
    new_content = content
    contentlines = content.splitlines()
    new_content_lines = []
    if cwd in {homebin, homebin2}:
        shebang = detect_shebang(content)
        match shebang:
            case "python":
                new_content_lines[0] = TERMUX_PYTHON
                new_content_lines.extend(contentlines[1:])
                new_content = "\n".join(new_content_lines)
            case "python2":
                new_content_lines[0] = TERMUX_PYTHON
                new_content_lines.extend(contentlines)
                new_content = "\n".join(new_content_lines)
            case "bash":
                new_content_lines[0] = TERMUX_BASH
                new_content_lines.extend(contentlines[1:])
                new_content = "\n".join(new_content_lines)
            case "bash2":
                new_content_lines[0] = TERMUX_BASH
                new_content_lines.extend(contentlines)
                new_content = "\n".join(new_content_lines)
    out_file.write_text(new_content, encoding="utf-8")
    if cwd in {homebin, homebin2}:
        out_file.chmod(493)
        create_symlink(out_file)


if __name__ == "__main__":
    main()
