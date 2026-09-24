import sys
from collections.abc import Iterable, Sequence
from lib2to3.refactor import RefactoringTool, get_fixers_from_package
from multiprocessing import Pool
from pathlib import Path

WORKERS = 8


def all_fixers():
    return list(get_fixers_from_package("lib2to3.fixes"))


def fix_file(path_str):
    path = Path(path_str)
    try:
        original = path.read_text(encoding="utf-8")
        tool = RefactoringTool(all_fixers())
        refactored = tool.refactor_string(original, path_str)
        if refactored and refactored != original:
            path.write_text(refactored, encoding="utf-8")
            return path_str, True, "changed"
        return path_str, True, "unchanged"
    except SyntaxError as e:
        return path_str, False, f"syntax error: {e}"
    except Exception as e:
        return path_str, False, f"error: {e!s}"


def find_files(paths, exts=(".py",)):
    found = []
    for p in paths:
        path = Path(p)
        if path.is_file() and path.suffix in exts:
            found.append(str(path))
        elif path.is_dir():
            for ext in exts:
                found.extend(str(f) for f in path.rglob(f"*{ext}"))
    return list(dict.fromkeys(found))


def main():
    args = sys.argv[1:] or ["."]
    files = find_files(args)
    if not files:
        print("No Python files found.")
        return 1
    print(f"Processing {len(files)} file(s) with {WORKERS} workers")
    failed = 0
    with Pool(WORKERS) as pool:
        results = [pool.apply_async(fix_file, (f,)) for f in files]
        for i, r in enumerate(results, 1):
            path, ok, msg = r.get()
            print(f"[{i}/{len(files)}] {'✓' if ok else '✗'} {Path(path).name} — {msg}")
            if not ok:
                failed += 1
    print(f"\nDone. {len(files) - failed} ok, {failed} failed.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
