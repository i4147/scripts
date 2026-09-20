import os
import re
import sys
from pathlib import Path

TARGET_CODE = """ATTRIBUTES = {
    "bold": 1,
    "dark": 2,
    "italic": 3,
    "underline": 4,
    "blink": 5,
    "reverse": 7,
    "concealed": 8,
    "strike": 9,
}
HIGHLIGHTS = {
    "on_black": 40,
    "on_grey": 40,
    "on_red": 41,
    "on_green": 42,
    "on_yellow": 43,
    "on_blue": 44,
    "on_magenta": 45,
    "on_cyan": 46,
    "on_light_grey": 47,
    "on_dark_grey": 100,
    "on_light_red": 101,
    "on_light_green": 102,
    "on_light_yellow": 103,
    "on_light_blue": 104,
    "on_light_magenta": 105,
    "on_light_cyan": 106,
    "on_white": 107,
}
COLORS = {
    "black": 30,
    "grey": 30,
    "red": 31,
    "green": 32,
    "yellow": 33,
    "blue": 34,
    "magenta": 35,
    "cyan": 36,
    "light_grey": 37,
    "dark_grey": 90,
    "light_red": 91,
    "light_green": 92,
    "light_yellow": 93,
    "light_blue": 94,
    "light_magenta": 95,
    "light_cyan": 96,
    "white": 97,
}
RESET = "\\x1b[0m"


def can_colorize(*, no_color=None, force_color=None):
    if no_color is not None and no_color:
        return False
    if force_color is not None and force_color:
        return True
    if os.environ.get("ANSI_COLORS_DISABLED"):
        return False
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if os.environ.get("TERM") == "dumb":
        return False
    if not hasattr(sys.stdout, "fileno"):
        return False
    try:
        return os.isatty(sys.stdout.fileno())
    except OSError:
        return sys.stdout.isatty()


def colored(text, color=None, on_color=None, attrs=None, *, no_color=None, force_color=None):
    result = str(text)
    if not can_colorize(no_color=no_color, force_color=force_color):
        return result
    fmt_str = "\\x1b[%dm%s"
    rgb_fore_fmt_str = "\\x1b[38;2;%d;%d;%dm%s"
    rgb_back_fmt_str = "\\x1b[48;2;%d;%d;%dm%s"
    if color is not None:
        if isinstance(color, str):
            result = fmt_str % (COLORS[color], result)
        elif isinstance(color, tuple):
            result = rgb_fore_fmt_str % (color[0], color[1], color[2], result)
    if on_color is not None:
        if isinstance(on_color, str):
            result = fmt_str % (HIGHLIGHTS[on_color], result)
        elif isinstance(on_color, tuple):
            result = rgb_back_fmt_str % (on_color[0], on_color[1], on_color[2], result)
    if attrs is not None:
        for attr in attrs:
            result = fmt_str % (ATTRIBUTES[attr], result)
    result += RESET
    return result


def cprint(text, color=None, on_color=None, attrs=None, *, no_color=None, force_color=None, **kwargs):
    print(colored(text, color, on_color, attrs, no_color=no_color, force_color=force_color), **kwargs)
"""

IMPORT_STATEMENT = "from dh import cprint"


def add_import(content):
    lines = content.split("\n")

    last_import_index = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            last_import_index = i
        elif last_import_index != -1 and stripped.endswith(")"):
            last_import_index = i

    if IMPORT_STATEMENT in content:
        return content

    if last_import_index != -1:
        lines.insert(last_import_index + 1, IMPORT_STATEMENT)
    else:
        insert_pos = 0
        for i, line in enumerate(lines):
            if line.strip() and not line.startswith("#") and not line.startswith('"""') and not line.startswith("'''"):
                insert_pos = i
                break
        lines.insert(insert_pos, IMPORT_STATEMENT)

    return "\n".join(lines)


def remove_code_block(content):
    if TARGET_CODE in content:
        return content.replace(TARGET_CODE, "")

    pattern = r"ATTRIBUTES\s*=\s*\{[^}]*\}.*?def cprint\(.*?\)"
    match = re.search(pattern, content, re.DOTALL)
    if match:
        return content[: match.start()] + content[match.end() :]

    return content


def process_file(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        if "ATTRIBUTES" not in content or "def cprint" not in content:
            return False

        content = remove_code_block(content)

        content = add_import(content)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        return True
    except Exception as e:
        print(f"Error processing {filepath}: {e}")
        return False


def main():
    current_dir = Path.cwd()
    py_files = list(current_dir.glob("*.py"))

    script_name = Path(__file__).name
    py_files = [f for f in py_files if f.name != script_name]

    if not py_files:
        print("No .py files found in current directory.")
        return

    processed_count = 0
    for filepath in py_files:
        if process_file(filepath):
            print(f"Processed: {filepath.name}")
            processed_count += 1

    print(f"\nTotal files processed: {processed_count}/{len(py_files)}")


if __name__ == "__main__":
    main()
