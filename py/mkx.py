import os
import pathlib
import re
import stat


def update_shebang(filepath: str) -> bool:
    target_shebang = "#!/data/data/com.termux/files/usr/bin/python3\n"
    try:
        content = pathlib.Path(filepath).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    if content.startswith(target_shebang):
        return False
    shebang_pattern = "^#!.*python.*\\n"
    match = re.match(shebang_pattern, content)
    if match:
        existing_shebang = match.group(0)
        if existing_shebang != target_shebang:
            new_content = content.replace(existing_shebang, target_shebang, 1)
            pathlib.Path(filepath).write_text(new_content, encoding="utf-8")
            return True
    else:
        new_content = target_shebang + content
        pathlib.Path(filepath).write_text(new_content, encoding="utf-8")
        return True
    return False


def make_executable(filepath: str) -> bool | None:
    try:
        current_permissions = os.stat(filepath).st_mode
        new_permissions = current_permissions | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        pathlib.Path(filepath).chmod(new_permissions)
        return True
    except OSError:
        return False


def is_python_file(filepath: str) -> bool:
    if filepath.endswith(".py"):
        return True
    try:
        with pathlib.Path(filepath).open(encoding="utf-8") as f:
            first_line = f.readline()
            return "python" in first_line
    except (OSError, UnicodeDecodeError):
        return False


def main() -> None:
    changed_files = []
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for file in files:
            if file.startswith("."):
                continue
            filepath = os.path.join(root, file)
            rel_path = os.path.relpath(filepath)
            if rel_path == pathlib.Path(__file__).name:
                continue
            if is_python_file(filepath):
                if update_shebang(filepath):
                    if make_executable(filepath):
                        changed_files.append(rel_path)
                make_executable(filepath)
                print(f"{filepath}", end=" ")
                changed_files.append(rel_path)
    for file in changed_files:
        print(file)


if __name__ == "__main__":
    main()
