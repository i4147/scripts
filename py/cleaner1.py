import pathlib
import re
import sys


def clean_terminal_transcript(path: str) -> None:
    ansi_re = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    control_map = dict.fromkeys(range(32))
    control_map[9] = None
    control_map[10] = None
    control_map[13] = None
    try:
        content = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
        content = ansi_re.sub("", content)
        content = content.translate(control_map)
        pathlib.Path(path).write_text(content, encoding="utf-8")
        print(f"Cleaned: {pathlib.Path(path).name}")
    except Exception as e:
        print(
            f"Error processing {path}: {e}",
            file=sys.stderr,
        )
        sys.exit(1)


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {pathlib.Path(sys.argv[0]).name} <transcript_file>")
        sys.exit(1)
    fname = sys.argv[1]
    if not pathlib.Path(fname).is_file():
        print(f"Error: '{fname}' is not a file")
        sys.exit(1)
    clean_terminal_transcript(fname)


if __name__ == "__main__":
    main()
