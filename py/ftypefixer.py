import filetype


def correct_file_extensions(root_dir: str = ".", dry_run: bool = True) -> None:
    if dry_run:
        pass
    renames_count = 0
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for filename in filenames:
            current_path = Path(dirpath) / filename
            if not current_path.is_file():
                continue
            try:
                kind = filetype.guess(current_path)
                if kind is None:
                    continue
                detected_ext = kind.extension
                current_ext = current_path.suffix.lstrip(".")
                if current_ext.lower() != detected_ext.lower():
                    new_filename = f"{current_path.stem}.{detected_ext}"
                    new_path = current_path.with_name(new_filename)
                    if not dry_run:
                        if not new_path.exists():
                            current_path.rename(new_path)
                            renames_count += 1
            except Exception:
                pass
    if dry_run:
        pass


if __name__ == "__main__":
    correct_file_extensions(root_dir=".", dry_run=False)
