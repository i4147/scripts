from pathlib import Path

from fastwalk import walk_files


def fix_file(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    new_lines = []
    inside_class = False
    inside_main = False
    indenting_function = False
    current_indent = ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("if __name__"):
            inside_main = True
            inside_class = False
            indenting_function = False
        if stripped.startswith("class ") and stripped.endswith(":"):
            inside_class = True
            new_lines.append(line)
            continue
        if inside_class and not inside_main:
            if line.startswith("def "):
                indenting_function = True
                current_indent = "    "
                new_lines.append(current_indent + line)
                continue
            if indenting_function:
                if line.startswith("def "):
                    new_lines.append("    " + line)
                elif stripped == "":
                    new_lines.append(line)
                elif not line.startswith((" ", "\t")):
                    indenting_function = False
                    new_lines.append(line)
                else:
                    new_lines.append("    " + line)
                continue
        new_lines.append(line)
    path.write_text("\n".join(new_lines), encoding="utf-8")


if __name__ == "__main__":
    for pth in walk_files("."):
        path = Path(pth)
        if path.name == "fix_indent.py":
            continue
        if path.suffix == ".py":
            fix_file(path)
            print(f"Fixed: {path}")
