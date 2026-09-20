import os
from collections import defaultdict
from pathlib import Path

import click
from stringzilla import File, Sha256


def get_file_hash(file_path: Path):
    sha256 = Sha256()
    try:
        mapped_file = File(file_path)
        return sha256.update(mapped_file).hexdigest()
    except Exception as e:
        print(f"Error processing file {file_path}: {e}")
        return None


def find_duplicates(path: Path) -> int:
    files_by_hash = defaultdict(list)
    duplicate_count = 0
    for root, _, files in os.walk(path):
        for file in files:
            file_path = Path(root) / file
            try:
                file_hash = get_file_hash(file_path)
                if file_hash:
                    files_by_hash[file_hash].append(file_path)
            except Exception as e:
                print(f"Error processing file {file_path}: {e}")
                continue
    for (
        file_hash,
        file_paths,
    ) in files_by_hash.items():
        if len(file_paths) > 1:
            duplicate_count += len(file_paths) - 1
            print(f"Duplicate files found for hash {file_hash}:")
            for file_path in file_paths:
                relative_path = file_path.relative_to(path)
                print(f"  {relative_path}")
            print()
    return duplicate_count


@click.command()
@click.argument(
    "path",
    default=".",
    type=click.Path(
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
)
def report_duplicates(path) -> None:
    print(f"Searching for duplicates in directory: {path}")
    duplicate_count = find_duplicates(Path(path))
    print("\nSummary:")
    print(f"Number of duplicate groups found: {duplicate_count}")
    print("Duplicate detection process completed.")


if __name__ == "__main__":
    report_duplicates()
