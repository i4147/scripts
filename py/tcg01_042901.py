import subprocess
import sys
import shutil
from pathlib import Path
from datetime import datetime

TERMUX_SHEBANGS = {
    "python": "#!/data/data/com.termux/files/usr/bin/env python",
    "bash": "#!/data/data/com.termux/files/usr/bin/env bash",
    "sh": "#!/data/data/com.termux/files/usr/bin/env sh",
}
SCRIPT_DIRS = {Path.home() / "bin", Path.home() / "bashbin"}
ARCHIVE_DIR = Path.home() / "isaac" / "may" / "scripts"


def get_clipboard_content() -> str:
    try:
        result = subprocess.run(["termux-clipboard-get"], capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Failed to read clipboard: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("Error: termux-clipboard-get not found", file=sys.stderr)
        sys.exit(1)


def detect_language(content: str) -> str:
    first_line = content.lstrip().split("\n")[0] if content else ""
    if first_line.startswith("#!"):
        if "python" in first_line.lower():
            return "python"
        elif "bash" in first_line.lower() or "sh" in first_line.lower():
            return "bash"
    python_indicators = ["import ", "from ", "def ", "class ", "if __name__", "print("]
    bash_indicators = ["echo ", "cd ", "export ", "if [", "for ", "while ", "$("]
    preview = content.lower()
    python_score = sum(1 for ind in python_indicators if ind in preview)
    bash_score = sum(1 for ind in bash_indicators if ind in preview)
    return "python" if python_score >= bash_score else "bash"


def replace_shebang(content: str, lang: str) -> str:
    lines = content.splitlines()
    if lines and lines[0].startswith("#!"):
        lines.pop(0)
    if lang == "python":
        lines.insert(0, TERMUX_SHEBANGS["python"])
    else:
        lines.insert(0, TERMUX_SHEBANGS["bash"])
    result = "\n".join(lines)
    return result if result.endswith("\n") else result + "\n"


def archive_existing_file(file_path: Path) -> None:
    if not file_path.exists():
        return
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_name = f"{file_path.stem}_{timestamp}{file_path.suffix}"
    archive_path = ARCHIVE_DIR / archive_name
    counter = 1
    while archive_path.exists():
        archive_name = f"{file_path.stem}_{timestamp}_{counter}{file_path.suffix}"
        archive_path = ARCHIVE_DIR / archive_name
        counter += 1
    try:
        shutil.move(str(file_path), str(archive_path))
        print(f"📦 Archived existing file to: {archive_path}")
    except OSError as e:
        print(f"❌ Failed to archive file: {e}", file=sys.stderr)
        sys.exit(1)


def create_symlink(script_path: Path) -> None:
    if script_path.suffix:
        symlink_path = script_path.parent / script_path.stem
        if symlink_path.exists() and symlink_path.is_symlink():
            try:
                symlink_path.unlink()
            except OSError as e:
                print(f"  ⚠️  Failed to remove old symlink: {e}", file=sys.stderr)
        if not symlink_path.exists():
            try:
                symlink_path.symlink_to(script_path)
                print(f"  → Created symlink: {symlink_path.name}")
            except OSError as e:
                print(f"  ⚠️  Failed to create symlink: {e}", file=sys.stderr)


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <filename>", file=sys.stderr)
        sys.exit(1)
    filename = sys.argv[1]
    output_path = Path(filename)
    cwd = Path.cwd()
    is_script_dir = cwd in SCRIPT_DIRS or cwd.name == "bin"
    if output_path.exists():
        archive_existing_file(output_path)
    content = get_clipboard_content()
    if not content.strip():
        print("⚠️  Clipboard is empty, creating empty file")
        content = "\n"
        if is_script_dir:
            content = TERMUX_SHEBANGS["bash"] + "\n\n" + content
    elif is_script_dir:
        lang = detect_language(content)
        content = replace_shebang(content, lang)
        print(f"✓ Added {lang} shebang")
    try:
        output_path.write_text(content)
        print(f"✓ Created: {output_path}")
    except OSError as e:
        print(f"Error writing file: {e}", file=sys.stderr)
        sys.exit(1)
    if is_script_dir:
        output_path.chmod(493)
        create_symlink(output_path)


if __name__ == "__main__":
    main()
