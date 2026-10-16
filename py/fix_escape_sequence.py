import os
import re


def fix_invalid_escapes(filepath: str) -> None:
    fixed_lines = []
    made_change = False
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for i, line in enumerate(lines):
            modified_line = re.sub(r"\\(?!([nrt b\\\'\"]))", r"\\\\\\1", line)
            if modified_line != line:
                made_change = True
                fixed_lines.append(modified_line)
            else:
                fixed_lines.append(line)
        if made_change:
            with open(filepath, "w", encoding="utf-8") as f:
                f.writelines(fixed_lines)
            print(f"Fixed invalid escapes in: {filepath}")
    except Exception as e:
        print(f"Error processing {filepath}: {e}")


def process_directory(directory: str = ".") -> None:
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".py"):
                filepath = os.path.join(root, file)
                fix_invalid_escapes(filepath)


if __name__ == "__main__":
    print("Starting to fix invalid escape sequences in Python files...")
    process_directory()
    print("Finished processing all Python files.")
