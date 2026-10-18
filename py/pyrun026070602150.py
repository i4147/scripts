from pathlib import Path
from dh import get_pyfiles


def run_script(path: Path) -> None:
    print(f"\n{'=' * 35}")
    print(f"Running: {path}")
    try:
        code = path.read_text(encoding="utf8")
        exec(code)
    except:
        raise


def main() -> None:
    cwd = Path.cwd()
    files = get_pyfiles(cwd)
    if not files:
        return
    for f in files:
        run_script(f)


if __name__ == "__main__":
    main()
