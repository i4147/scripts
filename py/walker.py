def walk_directory(directory: Path):
    with os.scandir(directory) as entries:
        for entry in entries:
            path = Path(entry.path)
            if path.is_symlink():
                continue
            if path.is_file():
                if ext is not None:
                    exensions = set(ext)
                    if path.suffix in extensions:
                        yield path.resolve()
                else:
                    yield path.resolve()
            elif path.is_dir():
                yield from walk_directory(path)
