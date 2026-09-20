def archive_existing_file(file_path: Path) -> None:
    if not file_path.exists():
        return
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = ARCHIVE_DIR / file_path.name

    counter = 1
    while archive_path.exists():
        archive_name = f"{file_path.stem}_{counter}{file_path.suffix}"
        archive_path = ARCHIVE_DIR / archive_name
        counter += 1

    try:
        shutil.move(str(file_path), str(archive_path))
        print(f"📦 Archived to: {archive_path}")
    except OSError as e:
        print(f"❌ Failed to archive: {e}", file=sys.stderr)
        sys.exit(1)
