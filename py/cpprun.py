from __future__ import annotations

import sys

if __name__ == "__main__":
    args = sys.argv[1:]
    if args:
        for arg in args:
            if "*" in arg:
                p = glob_glob(arg)
                print(p)
