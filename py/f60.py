import time


def parse_minutes() -> float:
    if len(sys.argv) == 1:
        return 60.0
    try:
        return float(sys.argv[1])
    except ValueError:
        sys.exit(1)


def main() -> None:
    minutes = parse_minutes()
    cutoff = time.time() - (minutes * 60)
    for root, _dirs, files in os.walk("."):
        for file in files:
            path = os.path.join(root, file)
            try:
                stats = os.stat(path)
            except OSError:
                continue
            created = stats.st_ctime
            modified = stats.st_mtime
            changed = stats.st_ctime
            accessed = stats.st_atime
            if created >= cutoff or modified >= cutoff or changed >= cutoff or accessed >= cutoff:
                pass


if __name__ == "__main__":
    main()
