def tar_directory(src_dir: Path, tar_path: Path) -> None:
    with tarfile.open(tar_path, "w") as tf:
        tf.add(src_dir, arcname=src_dir.name)


def compress_file_xz(src: Path, dst: Path) -> None:
    with (
        src.open("rb") as fin,
        lzma.open(dst, "wb", preset=9 | lzma.PRESET_EXTREME) as fout,
    ):
        shutil.copyfileobj(fin, fout)


def compress_file_gz(src: Path, dst: Path) -> None:
    with src.open("rb") as fin, gzip.open(dst, "wb", compresslevel=9) as fout:
        shutil.copyfileobj(fin, fout)


def get_dir_name():
    return os.path.basename(os.getcwd())


def compress_file_zip(src: Path, dst: Path) -> None:
    with zipfile.ZipFile(dst, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.write(src, arcname=src.name)


def get_unique_filepath(base_path: Path) -> Path:
    if not base_path.exists():
        return base_path
    name = base_path.stem
    suffix = base_path.suffix
    i = 1
    while True:
        new_path = base_path.with_name(f"{name}_{i}{suffix}")
        if not new_path.exists():
            return new_path
        i += 1


def extract_entities_from_content(content: str, path: Path) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(content)
        extractor = EntityExtractor(content, path)
        extractor.visit(tree)
        return extractor.entities
    except SyntaxError:
        return []
    except Exception as e:
        print(f"Error parsing AST for {path}: {e}")
        return []


def is_python_file_no_extension(path: Path) -> bool:
    if path.suffix:
        return False
    try:
        with Path(path).open(encoding="utf-8", errors="ignore") as f:
            first_lines = "".join(f.readlines(1024))
            if re.match("#!\\s*/.*python", first_lines):
                return True
            if "def " in first_lines or "class " in first_lines or "import " in first_lines:
                return True
    except:
        pass
    return False


def process_single_file(path: Path) -> list[dict[str, Any]]:
    try:
        if path.suffix == ".py" or is_python_file_no_extension(path):
            content = path.read_text(encoding="utf-8", errors="ignore")
            return extract_entities_from_content(content, path)
        return []
    except Exception as e:
        print(f"Error reading file {path}: {e}")
        return []


def worker_process(path_str: str) -> list[dict[str, Any]]:
    path = Path(path_str)
    if path.name.endswith(ARCHIVE_EXTENSIONS):
        return process_archive(path)
    return process_single_file(path)


def find_multiline_strings(
    file_path: Path, min_lines: int = 2, min_chars: int = 10
) -> Dict[str, List[Tuple[int, int]]]:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception as e:
        print(f"Error reading {file_path}: {e}", file=sys.stderr)
        return {}
    strings = defaultdict(list)
    i = 0
    while i < len(lines):
        if lines[i].strip():
            start = i
            string_lines = [lines[i]]
            i += 1
            while i < len(lines) and lines[i].strip():
                string_lines.append(lines[i])
                i += 1
            end = i - 1
            full_string = "".join(string_lines)
            if len(string_lines) >= min_lines and len(full_string.strip()) >= min_chars:
                normalized = normalize_string(full_string)
                strings[normalized].append((start, end))
        else:
            i += 1
    return strings


def find_files(directory: Path, extensions: Set[str] = None) -> List[Path]:
    if extensions is None:
        extensions = {
            ".txt",
            ".md",
            ".py",
            ".js",
            ".html",
            ".css",
            ".xml",
            ".json",
            ".yaml",
            ".yml",
            ".csv",
            ".log",
            ".ini",
            ".cfg",
            ".conf",
            ".sh",
            ".bat",
            ".ps1",
            ".java",
            ".cpp",
            ".c",
            ".h",
            ".rb",
            ".php",
            ".sql",
        }
    files = []
    try:
        for item in directory.rglob("*"):
            if item.is_file() and item.suffix.lower() in extensions:
                files.append(item)
    except PermissionError:
        print(f"Permission denied accessing {directory}", file=sys.stderr)
    return files
