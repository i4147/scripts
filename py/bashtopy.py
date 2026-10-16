import re
import sys
from pathlib import Path


def extract_python_from_bash(bash_content):

    pattern = r'python3?\s*(?:-\s*)?<<\s*[\'"]?([A-Za-z_][A-Za-z0-9_]*)[\'"]?'

    match = re.search(pattern, bash_content)
    if not match:
        return None

    delimiter = match.group(1)

    line_end = bash_content.index("\n", match.start())

    end_pattern = rf"^{re.escape(delimiter)}\s*$"
    end_match = re.search(end_pattern, bash_content[line_end:], re.MULTILINE)

    if not end_match:
        return None

    python_code_start = line_end + 1
    python_code_end = line_end + end_match.start()

    return bash_content[python_code_start:python_code_end].strip()


def convert_bash_to_python(input_file):
    input_path = Path(input_file)

    try:
        bash_content = input_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Error reading {input_path}: {e}", file=sys.stderr)
        return None

    python_code = extract_python_from_bash(bash_content)

    if python_code is None:
        print(f"No Python heredoc found in {input_path}", file=sys.stderr)
        return None

    output_path = input_path.with_suffix(".py")

    try:
        output_path.write_text(python_code + "\n", encoding="utf-8")
        print(f"Created {output_path}")
        return output_path
    except Exception as e:
        print(f"Error writing {output_path}: {e}", file=sys.stderr)
        return None


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <bash_script>")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = convert_bash_to_python(input_file)

    if output_file:
        print(f"Successfully converted {input_file} to {output_file}")
        sys.exit(0)
    else:
        print(f"Failed to convert {input_file}")
        sys.exit(1)


if __name__ == "__main__":
    main()
