import argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from loguru import logger

SKIP_DIRS = {".git", "__pycache__", ".ruff_cache", ".pytest_cache"}


def strip_bash_comments(line):
    if line.startswith("#!"):
        return line, 0
    in_single_quote = False
    in_double_quote = False
    for i, char in enumerate(line):
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
        elif char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
        elif char == "#" and not in_single_quote and not in_double_quote:
            return line[:i].rstrip() + "\n", 1
    return line, 0


def is_bash_script(path: Path) -> bool:
    if path.suffix == ".sh":
        return True
    try:
        with path.open("r") as f:
            first_line = f.readline()
            return first_line.startswith("#!")
    except Exception:
        return False


def process_file(path: Path):
    try:
        cwd = Path.cwd()
        rel_path = path.relative_to(cwd)
        lines = path.read_text().splitlines(keepends=True)

        cleaned_lines = []
        total_removed = 0

        for line in lines:
            cleaned, count = strip_bash_comments(line)
            cleaned_lines.append(cleaned)
            total_removed += count

        if total_removed > 0:
            path.write_text("".join(cleaned_lines))
            logger.info(f"{rel_path}: removed {total_removed} comments")
            return total_removed

        return 0
    except Exception as e:
        logger.error(f"Failed {path}: {e}")
        return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("targets", nargs="*", type=str)
    args = parser.parse_args()

    targets = [Path(t) for t in args.targets] if args.targets else [Path(".")]
    files_to_process = []

    for target in targets:
        if target.is_file():
            if not any(part in SKIP_DIRS for part in target.parts) and is_bash_script(target):
                files_to_process.append(target)
        elif target.is_dir():
            for path in target.rglob("*"):
                if path.is_file() and not any(part in SKIP_DIRS for part in path.parts):
                    if is_bash_script(path):
                        files_to_process.append(path)

    with ProcessPoolExecutor() as executor:
        results = list(executor.map(process_file, files_to_process))

    total_comments_global = sum(results)
    logger.success(f"Cleanup complete. Total comments removed: {total_comments_global}")


if __name__ == "__main__":
    main()
