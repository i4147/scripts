import json
from pathlib import Path
from typing import List, TextIO

def main() -> None:
    dir_path: Path = Path('.')
    en_files: List[Path] = sorted(dir_path.glob('en.*.txt'))
    fa_files: List[Path] = sorted(dir_path.glob('fa.*.txt'))
    all_files: List[Path] = en_files + fa_files
    file_handles: List[TextIO] = [f.open('r', encoding='utf-8') for f in all_files]
    try:
        output_file: Path = dir_path / 'combined.json'
        with output_file.open('w', encoding='utf-8') as out:
            out.write('{\n')
            first: bool = True
            for i, lines in enumerate(zip(*file_handles), start=1):
                record: List[str] = [line.rstrip('\r\n') for line in lines]
                if not first:
                    out.write(',\n')
                out.write(f'  "{i}": ' + json.dumps(record, ensure_ascii=False))
                first = False
            out.write('\n}')
    finally:
        for fh in file_handles:
            fh.close()

if __name__ == '__main__':
    main()