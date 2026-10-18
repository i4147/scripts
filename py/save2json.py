import json
from pathlib import Path
from typing import List, TextIO


def main() -> None:
    dir_path: Path = Path(".")
    en_files: List[Path] = sorted(dir_path.glob("en.*.txt"))
    fa_files: List[Path] = sorted(dir_path.glob("fa.*.txt"))
    en_handles: List[TextIO] = [f.open("r", encoding="utf-8") for f in en_files]
    fa_handles: List[TextIO] = [f.open("r", encoding="utf-8") for f in fa_files]
    all_handles: List[TextIO] = en_handles + fa_handles
    en_out: TextIO = (dir_path / "en.json").open("w", encoding="utf-8")
    fa_out: TextIO = (dir_path / "fa.json").open("w", encoding="utf-8")
    try:
        en_out.write("{\n")
        fa_out.write("{\n")
        en_first: bool = True
        fa_first: bool = True
        for i, lines in enumerate(zip(*all_handles), start=1):
            en_lines: List[str] = [line.rstrip("\r\n") for line in lines[: len(en_handles)]]
            fa_lines: List[str] = [line.rstrip("\r\n") for line in lines[len(en_handles) :]]
            en_lines.sort()
            fa_lines.sort()
            if not en_first:
                en_out.write(",\n")
            en_out.write(f'  "{i}": ' + json.dumps(en_lines, ensure_ascii=False))
            en_first = False
            if not fa_first:
                fa_out.write(",\n")
            fa_out.write(f'  "{i}": ' + json.dumps(fa_lines, ensure_ascii=False))
            fa_first = False
        en_out.write("\n}")
        fa_out.write("\n}")
    finally:
        for h in all_handles:
            h.close()
        en_out.close()
        fa_out.close()


if __name__ == "__main__":
    main()
