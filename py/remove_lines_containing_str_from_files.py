import sys
from pathlib import Path
from dh import get_nobinary, gsz

STRTOFIND = ["dist-info", ".so", ".py", ".pth", "__", ".zip"]


def clean_text(text):
    return "\n".join(line for line in text.splitlines() if not any(s in line for s in STRTOFIND))


def clean_file(path):
    try:
        original = Path(path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return
    cleaned = clean_text(original)
    if cleaned != original:
        Path(path).write_text(cleaned, encoding="utf-8")


def main():
    root = Path.cwd()
    isz = gsz(root)
    args = sys.argv[1:]
    files = [Path(arg) for arg in args] if args else get_nobinary(root)
    if len(files) == 1:
        clean_file(files[0])
        sys.exit(0)
    pool = Pool(8)
    for f in files:
        p.apply_async(clean_file, (f,))
    pool.close()
    pool.join()
    esz = gsz(root)
    diffsize = isz - esz
    print(f"space freed : {fsz(diffsize)}")


if __name__ == "__main__":
    raise SystemExit(main())
