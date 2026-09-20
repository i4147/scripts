import os
import shutil
from collections import defaultdict
from pathlib import Path

import click
import xxhash
from stringzilla import File, Sha256


def hash_sha256(path: Path) -> str | None:
    try:
        if not path.is_file() or path.is_symlink():
            return None
        size = path.stat().st_size
        if size == 0:
            return None
        f = File(str(path))
        sha = Sha256()
        return sha.update(f).hexdigest()
    except Exception as exc:
        print(f"SHA256 error [{path}]: {exc}")
        return None


def hash_xxh64(path: Path) -> str | None:
    try:
        if not path.is_file() or path.is_symlink():
            return None
        size = path.stat().st_size
        if size == 0:
            return None
        h = xxhash.xxh64()
        with path.open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        return h.hexdigest()
    except Exception as exc:
        print(f"xxHash error [{path}]: {exc}")
        return None


HASH_ALGORITHMS = {
    "sha256": hash_sha256,
    "xxh64": hash_xxh64,
}


def find_and_symlink_duplicates(
    base: Path,
    dry_run: bool,
    backup_dir: Path | None,
    hash_func,
) -> int:
    files_by_hash = defaultdict(list)
    duplicate_total = 0
    for root, dirs, files in os.walk(base):
        if ".git" in dirs:
            dirs.remove(".git")
        for fname in files:
            p = Path(root) / fname
            if not p.is_file() or p.is_symlink():
                continue
            h = hash_func(p)
            if h:
                files_by_hash[h].append(p)
    for h, paths in files_by_hash.items():
        if len(paths) <= 1:
            continue
        original = paths[0]
        for dup in paths[1:]:
            try:
                if dup.is_symlink():
                    continue
                duplicate_total += 1
                if dry_run:
                    print(f"[DRY-RUN] Would replace: {dup} -> {original}")
                    continue
                if backup_dir:
                    backup_target = backup_dir / dup.relative_to(base)
                    backup_target.parent.mkdir(
                        parents=True,
                        exist_ok=True,
                    )
                    shutil.move(
                        str(dup),
                        str(backup_target),
                    )
                    print(f"Backed up: {dup} -> {backup_target}")
                else:
                    dup.unlink()
                dup.symlink_to(original)
                print(f"Linked: {dup} -> {original}")
            except Exception as exc:
                print(f"Symlink error [{dup}]: {exc}")
    return duplicate_total


@click.command(context_settings={"ignore_unknown_options": True})
@click.argument(
    "path",
    default=".",
    type=click.Path(
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
)
@click.option(
    "--algorithm",
    "-a",
    type=click.Choice(
        list(HASH_ALGORITHMS.keys()),
        case_sensitive=False,
    ),
    help="Hash algorithm: sha256 or xxh64",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Do not change anything. Show what would happen.",
)
@click.option(
    "--backup",
    is_flag=True,
    help="Before replacing duplicates, move original file into a backup directory.",
)
@click.option(
    "--backup-dir",
    type=click.Path(file_okay=False, dir_okay=True),
    default="duplicate-backup",
    show_default=True,
    help="Directory where backups are stored.",
)
def cli(path, algorithm, dry_run, backup, backup_dir) -> None:
    if algorithm is None and not dry_run and not backup:
        algorithm = "xxh64"
        dry_run = True
    if algorithm is None:
        algorithm = "sha256"
    print(f"Scanning: {path}")
    print(f"Algorithm: {algorithm}")
    print(f"Dry-run: {dry_run}")
    print(f"Backup enabled: {backup and not dry_run}")
    hash_func = HASH_ALGORITHMS[algorithm.lower()]
    base = Path(path)
    backup_dir_path = Path(backup_dir).resolve() if (backup and not dry_run) else None
    count = find_and_symlink_duplicates(base, hash_func, dry_run, backup_dir_path)
    print(f"\nCompleted. Duplicate files processed: {count}")


if __name__ == "__main__":
    cli()
