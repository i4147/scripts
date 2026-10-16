import json
import sys
from pathlib import Path

from dh import get_random_filename
from loguru import logger


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object (dict).")
    return data


def unique_path(base: Path) -> Path:
    if not base.exists():
        return base
    stem = base.stem
    suffix = base.suffix
    i = 1
    while True:
        candidate = base.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def discover_inputs() -> list[Path]:
    return sorted(Path.cwd().glob("*.json"))


def collect_inputs(argv: list[str]) -> list[Path]:
    if not argv:
        paths = discover_inputs()
        if not paths:
            logger.error("No .json files found in the current directory.")
            sys.exit(1)
        logger.info(f"No CLI args provided — merging {len(paths)} .json file(s) from cwd.")
        return paths

    paths = []
    for arg in argv:
        path = Path(arg)
        if not path.is_file():
            logger.error(f"File not found: {path}")
            sys.exit(1)
        paths.append(path)
    return paths


def main():
    input_paths = collect_inputs(sys.argv[1:])

    merged: dict = {}

    origin: dict = {}
    duplicates: list = []

    for path in input_paths:
        data = load_json(path)
        for key, value in data.items():
            if key in merged:
                same = merged[key] == value
                duplicates.append((key, origin[key], path, same))
                logger.warning(
                    f"Duplicate key '{key}' in {path.name} "
                    f"(first seen in {origin[key].name}) — "
                    f"{'same value, keeping' if same else 'overriding with new value'}"
                )
            merged[key] = value
            origin[key] = path

    output_filename = get_random_filename() + ".json"
    output_path = unique_path(Path(output_filename))

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    logger.success(f"Merged {len(input_paths)} files → {output_path} ({len(merged)} records)")

    if duplicates:
        logger.info(f"Encountered {len(duplicates)} duplicate key(s) across inputs.")
    else:
        logger.info("No duplicate keys found across inputs.")

    for path in input_paths:
        try:
            path.unlink()
            logger.debug(f"Deleted input file: {path}")
        except OSError as e:
            logger.error(f"Failed to delete {path}: {e}")

    logger.success(f"Removed {len(input_paths)} input file(s).")


if __name__ == "__main__":
    main()
