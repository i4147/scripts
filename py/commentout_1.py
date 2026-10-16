import sys
from multiprocessing import Pool
from pathlib import Path
from tempfile import NamedTemporaryFile
from loguru import logger

POOL_SIZE = 8
CHUNK_SIZE = 10_000
DEFAULT_COMMENT = "#"
COMMENT_MAP = {
    ".vim": '"',
    ".lua": "--",
    ".py": "#",
    ".sh": "#",
    ".toml": "#",
    ".yml": "#",
    ".yaml": "#",
    ".js": "//",
    ".ts": "//",
    ".cpp": "//",
    ".c": "//",
    ".cs": "//",
    ".java": "//",
    ".sql": "--",
    ".rb": "#",
}


def process_chunk(lines, comment_char):
    processed = []
    for line in lines:
        stripped = line.lstrip()
        if not stripped or stripped.startswith(comment_char):
            processed.append(line)
        else:
            processed.append(f"{comment_char}{line}")
    return processed


def _parse_args(argv):
    if not 3 <= len(argv) <= 4:
        logger.error("Usage: python commentout.py <filename> <start_line> [end_line]")
        raise SystemExit(1)
    file_path = Path(argv[1])
    if not file_path.exists():
        logger.error("File {} not found.", file_path)
        raise SystemExit(1)
    try:
        start_line = int(argv[2])
        end_line = int(argv[3]) if len(argv) == 4 else None
    except ValueError:
        logger.error("Line numbers must be integers.")
        raise SystemExit(1)
    return file_path, start_line, end_line


def _resolve_comment_char(file_path):
    ext = file_path.suffix.lower()
    comment_char = COMMENT_MAP.get(ext)
    if comment_char is None:
        logger.warning(
            "Unknown extension {}. Using default '{}' as comment char.",
            ext,
            DEFAULT_COMMENT,
        )
        return DEFAULT_COMMENT
    return comment_char


def main(argv=None):
    args = list(argv) if argv is not None else sys.argv
    file_path, start_line, end_line = _parse_args(args)
    comment_char = _resolve_comment_char(file_path)
    target_end = end_line if end_line is not None else sys.maxsize
    with (
        file_path.open("r", encoding="utf-8", errors="ignore") as infile,
        NamedTemporaryFile("w", delete=False, dir=file_path.parent, encoding="utf-8") as temp_file,
    ):
        temp_path = Path(temp_file.name)
        current_line_idx = 1
        with Pool(processes=POOL_SIZE) as pool:
            while True:
                raw = [infile.readline() for _ in range(CHUNK_SIZE)]
                lines = [line for line in raw if line]
                if not lines:
                    break
                chunk_start = current_line_idx
                chunk_end = current_line_idx + len(lines) - 1
                if chunk_start <= target_end and chunk_end >= start_line:
                    prefix_count = max(0, start_line - chunk_start)
                    suffix_start = max(0, target_end - chunk_start + 1) if end_line is not None else len(lines)
                    prefix = lines[:prefix_count]
                    target_block = lines[prefix_count:suffix_start]
                    suffix = lines[suffix_start:]
                    async_result = pool.apply_async(process_chunk, (target_block, comment_char))
                    temp_file.writelines(prefix)
                    temp_file.writelines(async_result.get())
                    temp_file.writelines(suffix)
                else:
                    temp_file.writelines(lines)
                current_line_idx += len(lines)
    temp_path.replace(file_path)
    logger.info("Successfully processed {} using '{}'", file_path, comment_char)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
