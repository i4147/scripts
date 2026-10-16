import argparse
import shutil
import sys
from pathlib import Path

from dh import unique_path


def safe_move(
    source, destination, verbose: bool = False, no_clobber: bool = True
) -> tuple[bool, tuple[Path, Path]] | tuple[bool, None]:
    source_path = Path(source)
    if not source_path.exists():
        print(f"Error: Source '{source}' does not exist", file=sys.stderr)
        return False, None
    dest_path = Path(destination)
    if dest_path.is_dir():
        dest_path = dest_path / source_path.name
    original_dest = dest_path
    if no_clobber and dest_path.exists():
        dest_path = unique_path(dest_path)
        if verbose:
            print(f"Target exists. Renaming to: {dest_path}")
    try:
        shutil.move(str(source_path), str(dest_path))
        if verbose:
            print(f"moved '{source_path}' -> '{dest_path}'")
        return True, (source_path, dest_path)
    except Exception as e:
        print(f"Error moving file: {e}", file=sys.stderr)
        return False, None


def rollback(moves, verbose: bool = False) -> None:
    for src, dst in reversed(moves):
        try:
            if dst.exists():
                shutil.move(str(dst), str(src))
                if verbose:
                    print(f"rolled back '{dst}' -> '{src}'")
        except Exception as e:
            print(f"Rollback failed for {dst}: {e}", file=sys.stderr)


def parse_sources(raw_list):
    cleaned = []
    for item in raw_list:
        parts = [p for p in item.split(",") if p.strip()]
        cleaned.extend(parts)
    return cleaned


def main():
    parser = argparse.ArgumentParser(
        description="Safe mv — move files without overwriting, with rollback on error",
    )
    parser.add_argument(
        "sources",
        nargs="+",
        help="Source files/directories to move (comma-separated allowed)",
    )
    parser.add_argument("-d", "--dest", help="Destination path")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-f", "--force", action="store_true")
    parser.add_argument("-n", "--no-clobber", action="store_true")
    args = parser.parse_args()
    source_list = parse_sources(args.sources)
    no_clobber = not args.force if not args.no_clobber else True
    if len(source_list) > 1:
        dest_path = Path(args.destination)
        if not dest_path.exists():
            try:
                dest_path.mkdir(parents=True)
                if args.verbose:
                    print(f"Created directory: {dest_path}")
            except Exception as e:
                print(f"Error creating directory: {e}", file=sys.stderr)
                sys.exit(1)
        if not dest_path.is_dir():
            print(
                "Error: When moving multiple items, destination must be a directory",
                file=sys.stderr,
            )
            sys.exit(1)
    moves_done = []
    try:
        for source in source_list:
            ok, move_record = safe_move(source, args.destination, args.verbose, no_clobber)
            if not ok:
                raise RuntimeError(f"Move failed for {source}")
            if move_record:
                moves_done.append(move_record)
    except Exception as e:
        print(f"Error: {e}. Rolling back...", file=sys.stderr)
        rollback(moves_done, args.verbose)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
