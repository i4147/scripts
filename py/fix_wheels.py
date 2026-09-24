from __future__ import annotations

import os
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor


def _process_one(whl_path: str) -> str:
    path = Path(whl_path)

    if not path.is_file():
        return f"SKIP {path.name} (not a file)"

    target_name = path.name

    import zipfile

    try:
        with zipfile.ZipFile(path, "r") as zf:
            members = zf.namelist()
            if target_name not in members:
                return f"KEEP {path.name}"

            tmp_path = path.with_suffix(path.suffix + ".tmp")

            with (
                zipfile.ZipFile(path, "r") as src,
                zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as dst,
            ):
                for info in src.infolist():
                    if info.filename == target_name:
                        continue

                    dst.writestr(info, src.read(info.filename))

        os.replace(tmp_path, path)
        return f"UPDATED {path.name} (removed {target_name} from contents)"
    except Exception as e:
        return f"ERROR {path.name}: {e!r}"


def main() -> None:
    cwd = Path(".").resolve()
    whls = [p for p in cwd.iterdir() if p.is_file() and p.suffix == ".whl"]

    if not whls:
        return

    workers = max(1, os.cpu_count() or 1)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(_process_one, (str(p) for p in whls)))

    for r in results:
        print(r)


if __name__ == "__main__":
    main()
