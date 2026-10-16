import sys
from pathlib import Path


def samefile(path1, path2):
    try:
        return Path(path1).samefile(path2)
    except FileNotFoundError:
        return False
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return False
