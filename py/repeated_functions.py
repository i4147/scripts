def create_tar_archive(source_dir: Path, output_path: Path) -> bool:
    try:
        with tarfile.open(output_path, "w") as tar:
            for item in source_dir.rglob("*"):
                if item.is_file():
                    arcname = item.relative_to(source_dir.parent)
                    tar.add(item, arcname=arcname)
        return True
    except Exception as e:
        print(f"  Failed to create tar archive: {e}")
        return False


def extract_tar_archive(tar_path: Path, extract_dir: Path) -> bool:
    try:
        with tarfile.open(tar_path, "r") as tar:
            tar.extractall(path=extract_dir)
        return True
    except Exception as e:
        print(f"  Failed to extract tar archive: {e}")
        return False


def extract_file(src: bytes, tree: Tree) -> list[str]:
    root = tree.root_node
    return [src[node.start_byte : node.end_byte].decode() for node in root.children if node.type in VALID]


def get_all_files(root: str = "."):
    file_paths = []
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            full_path = os.path.join(dirpath, f)
            file_paths.append(full_path)
    return file_paths


def copy_groups(groups, output_dir="output") -> None:
    Path(output_dir).mkdir(exist_ok=True, parents=True)
    for idx, group in enumerate(groups, start=1):
        group_dir = os.path.join(output_dir, f"group_{idx}")
        Path(group_dir).mkdir(exist_ok=True, parents=True)
        for f in group:
            try:
                shutil.move(f, group_dir)
            except Exception as e:
                print(f"Failed to copy {f}: {e}")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(processName)s %(message)s",
        handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
    )


def main() -> None:
    args = sys.argv[1:]
    cwd = Path.cwd()
    before = gsz(cwd)
    files = [Path(p) for p in args] if args else get_files(cwd, ext=[".css", ".min.css"])
    _ = mpf3(process_file, files)
    diff_size = before - gsz(cwd)
    cprint(f"space freed : {fsz(diff_size)}", "green")


def copy_chunks(src, dst, chunk_size: int = 1024 * 1024) -> None:
    while True:
        chunk = src.read(chunk_size)
        if not chunk:
            break
        dst.write(chunk)


def unique_destination(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stem = dest.stem
    suffix = dest.suffix
    parent = dest.parent
    counter = 1
    while True:
        new_dest = parent / f"{stem}_{counter}{suffix}"
        if not new_dest.exists():
            return new_dest
        counter += 1


def should_exclude(path: Path) -> bool:
    return any(part in EXCLUDE_DIRS for part in path.parts)


def extract_objects(code: str):
    if TREE_SITTER_AVAILABLE:
        return extract_with_tree_sitter(code)
    return extract_with_ast(code)


def is_chinese_text(text: str, threshold: float = 0.3) -> bool:
    clean_text = "".join(text.split())
    if not clean_text:
        return False
    chinese_chars = len(CHINESE_PATTERN.findall(clean_text))
    return chinese_chars / len(clean_text) >= threshold


def get_relative_path(file_path: Path, base_path: Path) -> Path:
    try:
        return file_path.relative_to(base_path)
    except ValueError:
        return file_path


def should_skip_directory(dir_name: str) -> bool:
    if dir_name in SKIP_DIRS:
        return True
    return any(fnmatch.fnmatch(dir_name, pattern) for pattern in SKIP_DIR_PATTERNS)


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


def process_single_file(path: Path) -> list[dict[str, Any]]:
    try:
        if path.suffix == ".py" or is_python_file_no_extension(path):
            content = path.read_text(encoding="utf-8", errors="ignore")
            return extract_entities_from_content(content, path)
        return []
    except Exception as e:
        print(f"Error reading file {path}: {e}")
        return []


def is_english(text: str) -> bool:
    return not NON_ENGLISH_PATTERN.search(text)


def validate_repo_format(repo: str) -> bool:
    parts = repo.split("/")
    return len(parts) == 2 and all(parts)


def run_git_command(args: list[str]) -> str:
    try:
        result = subprocess.run(["git"] + args, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"❌ Git error executing {' '.join(e.cmd)}:\n{e.stderr.strip()}")
        sys.exit(1)


def main():
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = []
    if args:
        for arg in args:
            p = Path(arg)
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                files.extend(get_files(p))
    else:
        files = get_files(cwd)
    if len(files) == 1:
        process_file(files[0])
        sys.exit(1)
    mpf3(process_file, files)


def human_bytes(n: int) -> str:
    sign = "-" if n < 0 else ""
    n = abs(n)
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    return f"{sign}{n:.2f} {units[i]}" if units[i] != "B" else f"{sign}{int(n)} B"


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def is_git_repo(path: Path) -> bool:
    return (path / ".git").is_dir()


def split_into_chunks(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


def _encode_varint(value: int) -> bytes:
    result = bytearray()
    while value >= 128:
        result.append(value & 127 | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def _hash_4_bytes(data: bytes, pos: int) -> int:
    val = data[pos] | data[pos + 1] << 8 | data[pos + 2] << 16 | data[pos + 3] << 24
    return val * 506832829 >> 32 - 14 & _HASH_TABLE_SIZE - 1


def _emit_literal(output: bytearray, data: bytes, start: int, length: int) -> None:
    if length <= 0:
        return
    if length <= 60:
        output.append(length - 1 << 2)
    elif length <= 256:
        output.append(60 << 2)
        output.append(length - 1)
    elif length <= 65536:
        output.append(61 << 2)
        output.append(length - 1 & 255)
        output.append(length - 1 >> 8 & 255)
    elif length <= 16777216:
        output.append(62 << 2)
        output.append(length - 1 & 255)
        output.append(length - 1 >> 8 & 255)
        output.append(length - 1 >> 16 & 255)
    else:
        output.append(63 << 2)
        output.append(length - 1 & 255)
        output.append(length - 1 >> 8 & 255)
        output.append(length - 1 >> 16 & 255)
        output.append(length - 1 >> 24 & 255)
    output.extend(data[start : start + length])


def _emit_copy(output: bytearray, offset: int, length: int) -> None:
    while length > 0:
        if length >= 4 and length <= 11 and (offset <= _MAX_OFFSET_1):
            tag = 1 | length - 4 << 2 | offset >> 8 << 5
            output.append(tag)
            output.append(offset & 255)
            return
        if offset <= _MAX_OFFSET_2:
            copy_len = min(length, 64)
            tag = 2 | copy_len - 1 << 2
            output.append(tag)
            output.append(offset & 255)
            output.append(offset >> 8 & 255)
            length -= copy_len
        else:
            copy_len = min(length, 64)
            tag = 3 | copy_len - 1 << 2
            output.append(tag)
            output.append(offset & 255)
            output.append(offset >> 8 & 255)
            output.append(offset >> 16 & 255)
            output.append(offset >> 24 & 255)
            length -= copy_len


def compress(data: bytes) -> bytes:
    if not data:
        return _encode_varint(0)
    data_len = len(data)
    output = bytearray()
    output.extend(_encode_varint(data_len))
    if data_len < 4:
        _emit_literal(output, data, 0, data_len)
        return bytes(output)
    hash_table = [0] * _HASH_TABLE_SIZE
    pos = 0
    literal_start = 0
    while pos <= data_len - 4:
        h = _hash_4_bytes(data, pos)
        candidate = hash_table[h]
        hash_table[h] = pos
        if (
            (candidate > 0 or (candidate == 0 and pos > 0))
            and pos - candidate <= _MAX_OFFSET_2
            and (data[candidate : candidate + 4] == data[pos : pos + 4])
        ):
            if pos > literal_start:
                _emit_literal(output, data, literal_start, pos - literal_start)
            offset = pos - candidate
            match_len = 4
            max_match = min(data_len - pos, 64)
            while match_len < max_match and data[candidate + match_len] == data[pos + match_len]:
                match_len += 1
            _emit_copy(output, offset, match_len)
            pos += match_len
            literal_start = pos
            if pos <= data_len - 4:
                hash_table[_hash_4_bytes(data, pos - 1)] = pos - 1
        else:
            pos += 1
    if literal_start < data_len:
        _emit_literal(output, data, literal_start, data_len - literal_start)
    return bytes(output)


def ensure_dirs() -> None:
    ERROR_DIR.mkdir(exist_ok=True)
    OK_DIR.mkdir(exist_ok=True)


def gather_python_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if p.is_file()]


def worker(args):
    return process_file(*args)


def get_sha256(path: str | Path) -> str:
    path = Path(path)
    h = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def is_media_file(path: Path) -> bool:
    return path.suffix.lower() in MEDIA_EXTENSIONS


def compress_file(
    filepath: Path, preset: int = 9, threads: int = 4, remove_orig: bool = True
) -> tuple[Path, bool, str, int, int]:
    try:
        with open(filepath, "rb") as f:
            data = f.read()
        original_size = len(data)
        compressed = lzma_mt.compress(data, preset=preset, threads=threads)
        len(compressed)
        output_path = filepath.parent / (filepath.name + ".xz")
        with open(output_path, "wb") as f:
            f.write(compressed)
        space_freed = 0
        if remove_orig:
            filepath.unlink()
            space_freed = original_size
        return (filepath, True, f"Compressed to {output_path.name}", original_size, space_freed)
    except Exception as e:
        return filepath, False, f"Error: {e!s}", 0, 0


def decompress_file(filepath: Path, remove_orig: bool = True) -> tuple[Path, bool, str, int, int]:
    try:
        if filepath.suffix.lower() != ".xz":
            return filepath, False, "Error: Not an .xz file", 0, 0
        with open(filepath, "rb") as f:
            data = f.read()
        compressed_size = len(data)
        decompressed = lzma_mt.decompress(data)
        output_path = filepath.parent / filepath.stem
        with open(output_path, "wb") as f:
            f.write(decompressed)
        space_freed = 0
        if remove_orig:
            filepath.unlink()
            space_freed = compressed_size
        return (filepath, True, f"Decompressed to {output_path.name}", compressed_size, space_freed)
    except Exception as e:
        return filepath, False, f"Error: {e!s}", 0, 0


def format_bytes(bytes_val: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_val < 1024.0:
            return f"{bytes_val:.2f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.2f} PB"


def dir_size_bytes(path):
    total = 0
    path = Path(path)
    for root, dirs, files in os.walk(path):
        root_p = Path(root)
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            fp = root_p / name
            try:
                st = fp.stat()
                total += st.st_size
            except OSError:
                continue
    return total


def is_within_directory(directory, target):
    directory = Path(directory).resolve()
    target = Path(target).resolve()
    return directory == target or directory in target.parents


def safe_extract_stream(tar, dest_dir):
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    for member in tar:
        if member is None:
            continue
        name = member.name
        target_path = dest_dir / name
        if not is_within_directory(dest_dir, target_path):
            continue
        tar.extract(member, path=str(dest_dir))


def format_size(size_bytes):
    size_bytes = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def find_dist_info_dir(site_packages: Path, pkg_name: str) -> Path:
    candidates = list(site_packages.glob(f"{pkg_name}-*.dist-info"))
    if not candidates:
        norm = pkg_name.replace("-", "_")
        candidates = list(site_packages.glob(f"{norm}-*.dist-info"))
    if not candidates:
        raise FileNotFoundError(msg)
    if len(candidates) > 1:
        logger.warning("Multiple dist-info directories found for '{}', using: {}", pkg_name, candidates[0])
    return candidates[0]


def size_to_mb(size_str: str) -> float | None:
    match = re.search(r"([\d.]+)\s*Mi?B", size_str)
    if match:
        return float(match.group(1))
    return None


def sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def safe_read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed reading {path}: {e}")
        return None


def safe_write_text(path: Path, content: str) -> bool:
    try:
        path.write_text(content, encoding="utf-8")
        return True
    except Exception as e:
        logger.error(f"Failed writing {path}: {e}")
        return False


def normalize_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")


def extract_with_tree_sitter(code: str):
    objects = []
    try:
        parser = Parser()
        parser.language = Language(tree_sitter_python.language())
        tree = parser.parse(code.encode("utf-8"))
        root = tree.root_node
        for node in root.children:
            if node.type in ("function_definition", "class_definition"):
                name_node = node.child_by_field_name("name")
                if not name_node:
                    continue
                name = code[name_node.start_byte : name_node.end_byte]
                snippet = code[node.start_byte : node.end_byte]
                kind = "function" if node.type == "function_definition" else "class"
                objects.append(
                    {
                        "name": name,
                        "kind": kind,
                        "snippet": snippet,
                        "start_byte": node.start_byte,
                        "end_byte": node.end_byte,
                    }
                )
            elif node.type == "expression_statement":
                text = code[node.start_byte : node.end_byte]
                try:
                    parsed = ast.parse(text)
                    if len(parsed.body) == 1 and isinstance(parsed.body[0], ast.Assign):
                        assign = parsed.body[0]
                        if all((isinstance(t, ast.Name) for t in assign.targets)):
                            name = assign.targets[0].id
                            objects.append(
                                {
                                    "name": name,
                                    "kind": "constant",
                                    "snippet": text,
                                    "start_byte": node.start_byte,
                                    "end_byte": node.end_byte,
                                }
                            )
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"Tree-sitter failed; falling back to ast: {e}")
        return extract_with_ast(code)
    return objects


def extract_with_ast(code: str):
    objects = []
    try:
        tree = ast.parse(code)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                snippet = ast.get_source_segment(code, node)
                if snippet is None:
                    continue
                objects.append(
                    {
                        "name": node.name,
                        "kind": "function",
                        "snippet": snippet,
                        "start_byte": None,
                        "end_byte": None,
                        "lineno": node.lineno,
                        "end_lineno": getattr(node, "end_lineno", None),
                    }
                )
            elif isinstance(node, ast.ClassDef):
                snippet = ast.get_source_segment(code, node)
                if snippet is None:
                    continue
                objects.append(
                    {
                        "name": node.name,
                        "kind": "class",
                        "snippet": snippet,
                        "start_byte": None,
                        "end_byte": None,
                        "lineno": node.lineno,
                        "end_lineno": getattr(node, "end_lineno", None),
                    }
                )
            elif isinstance(node, ast.Assign):
                if all((isinstance(t, ast.Name) for t in node.targets)):
                    snippet = ast.get_source_segment(code, node)
                    if snippet is None:
                        continue
                    objects.append(
                        {
                            "name": node.targets[0].id,
                            "kind": "constant",
                            "snippet": snippet,
                            "start_byte": None,
                            "end_byte": None,
                            "lineno": node.lineno,
                            "end_lineno": getattr(node, "end_lineno", None),
                        }
                    )
    except Exception as e:
        logger.error(f"AST parsing failed: {e}")
    return objects


def is_supported_archive(path: Path) -> bool:
    s = str(path).lower()
    return any((s.endswith(ext) for ext in SUPPORTED_ARCHIVES))


def should_skip_dir(path: Path) -> bool:
    skip_names = {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".tox",
        ".nox",
        ".venv",
        "venv",
        "env",
        ".eggs",
        "site-packages",
    }
    return path.name in skip_names


def collect_python_files(base: Path):
    files = []

    def walk(p: Path):
        if should_skip_dir(p):
            return
        try:
            for item in p.iterdir():
                if item.is_dir():
                    walk(item)
                elif item.is_file():
                    if item.suffix == ".py":
                        files.append(item)
                    elif is_supported_archive(item):
                        extracted_dir = extract_archive(item)
                        for py_file in Path(extracted_dir).rglob("*.py"):
                            files.append(py_file)
        except PermissionError:
            logger.warning(f"Permission denied: {p}")

    walk(base)
    return files


def process_file(path_str: str):
    path = Path(path_str)
    code = safe_read_text(path)
    if not code:
        return []
    code = normalize_newlines(code)
    objs = extract_objects(code)
    result = []
    for obj in objs:
        snippet = obj["snippet"].strip()
        if not snippet:
            continue
        result.append(
            {
                "file": str(path),
                "name": obj["name"],
                "kind": obj["kind"],
                "snippet": obj["snippet"],
                "hash": sha256(snippet),
                "start_byte": obj.get("start_byte"),
                "end_byte": obj.get("end_byte"),
                "lineno": obj.get("lineno"),
                "end_lineno": obj.get("end_lineno"),
            }
        )
    return result


def get_utils_path(base: Path) -> Path:
    default_path = base / "utils.py"
    if not default_path.exists():
        return default_path
    i = 1
    while True:
        candidate = base / f"utils_{i}.py"
        if not candidate.exists():
            return candidate
        i += 1


def build_import_line(utils_module_name: str, names) -> str:
    names = sorted(set(names))
    return f"from {utils_module_name} import ({', '.join(names)})\n"


def insert_import_after_shebang(code: str, import_line: str) -> str:
    lines = code.splitlines(keepends=True)
    if not lines:
        return import_line
    insert_at = 0
    if lines[0].startswith("#!"):
        insert_at = 1
    joined = "".join(lines)
    if import_line in joined:
        return joined
    lines.insert(insert_at, import_line)
    return "".join(lines)


def update_file_for_move(path: Path, objects_to_remove, utils_module_name: str) -> bool:
    code = safe_read_text(path)
    if code is None:
        return False
    code = normalize_newlines(code)
    names = [obj["name"] for obj in objects_to_remove]
    new_code = remove_snippets_from_code(code, objects_to_remove)
    try:
        ast.parse(new_code)
    except SyntaxError as e:
        logger.error(f"Skipping {path}: code after removal is invalid: {e}")
        return False
    import_line = build_import_line(utils_module_name, names)
    new_code = insert_import_after_shebang(new_code, import_line)
    try:
        ast.parse(new_code)
    except SyntaxError as e:
        logger.error(f"Skipping {path}: code after adding import is invalid: {e}")
        return False
    return safe_write_text(path, new_code)


def format_size(size_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_const_name(name: str) -> bool:
    return name.isupper()


def should_skip_dir(dirname):
    return dirname in SKIP_DIRS


def has_shebang(filepath):
    try:
        with open(filepath, "rb") as f:
            first_line = f.readline()
            return first_line.startswith(b"#!")
    except OSError:
        return False


def fetch_content_length(url: str) -> int | None:
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            length = response.headers.get("Content-Length")
            if length:
                return int(length)
    except urllib.error.HTTPError as e:
        if e.code not in {405, 403}:
            raise
    request = urllib.request.Request(url, method="GET")
    request.add_header("Range", "bytes=0-0")
    with urllib.request.urlopen(request, timeout=10) as response:
        length = response.headers.get("Content-Length")
        return int(length) if length else None


def get_dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def extract_zst_file(archive_path, extract_path):
    output_path = extract_path / archive_path.stem
    with Path(archive_path).open("rb") as compressed_file:
        dctx = zstd.ZstdDecompressor()
        with Path(output_path).open("wb") as output_file:
            dctx.copy_stream(compressed_file, output_file)
    return output_path


def extract_tar_xz(archive_path, extract_path) -> None:
    with tarfile.open(archive_path, "r:xz") as tar:
        tar.extractall(path=extract_path, filter="data")


def find_archives(directory: Path) -> list[Path]:
    directory = Path(directory).resolve()
    archives = [zst_file for zst_file in directory.rglob("*.zst") if not zst_file.name.endswith(".tar.zst")]
    archives.extend(directory.rglob("*.tar.zst"))
    archives.extend(directory.rglob("*.tar.xz"))
    return sorted(set(archives))


def _frames_are_similar(a: np.ndarray, b: np.ndarray, threshold: float = 0.97) -> bool:
    small_a = cv2.resize(a, (64, 32))
    small_b = cv2.resize(b, (64, 32))
    diff = cv2.absdiff(small_a, small_b)
    similarity = 1.0 - diff.sum() / (diff.size * 255.0)
    return similarity >= threshold


def _merge_subtitles(subtitles: list[dict], gap_threshold: float = 1.0) -> list[dict]:
    if not subtitles:
        return []
    merged: list[dict] = []
    cur = dict(subtitles[0])
    for sub in subtitles[1:]:
        same_text = sub["text"] == cur["text"]
        close_enough = sub["start"] - cur["end"] <= gap_threshold
        if same_text and close_enough:
            cur["end"] = sub["end"]
        else:
            merged.append(cur)
            cur = dict(sub)
    merged.append(cur)
    return merged


def get_node_text(src: bytes, node) -> str:
    return src[node.start_byte : node.end_byte].decode()


def format_size(size_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def parse_minutes() -> float:
    if len(sys.argv) == 1:
        return 60.0
    try:
        return float(sys.argv[1])
    except ValueError:
        print("Invalid argument. Usage: script.py [minutes]")
        sys.exit(1)


def main() -> None:
    fonts = find_fonts()
    if not fonts:
        return
    html_content = generate_html(fonts)
    Path(OUTPUT_HTML).write_text(html_content, encoding="utf-8")
    print("font-preview.html created.")


def format_size(bytes_size: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} PB"


def load_dictionary(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    if not path.exists():
        logger.error("Error: Dictionary file %s not found", path)
        sys.exit(1)
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        fa_en = {str(k).strip(): str(v).strip() for k, v in data.items()}
        en_fa = {v: k for k, v in fa_en.items()}
        return (fa_en, en_fa)
    except Exception as e:
        logger.error("Error loading dictionary: %s", e)
        sys.exit(1)


def setup_readline(words: Iterable[str]) -> None:
    sorted_words = sorted(words)

    def completer(text: str, state: int) -> str | None:
        matches = [w for w in sorted_words if w.startswith(text)]
        return matches[state] if state < len(matches) else None

    readline.set_completer(completer)
    readline.parse_and_bind("tab: complete")
    readline.set_completer_delims(" \t\n")


def translate(word: str, fa_en: dict[str, str], en_fa: dict[str, str]) -> str | None:
    return fa_en.get(word) or en_fa.get(word)


def fuzzy_search(word: str, all_words: set[str], limit: int = 5, cutoff: float = 0.6) -> list[str]:
    return get_close_matches(word, all_words, n=limit, cutoff=cutoff)


def interactive_mode(fa_en: dict[str, str], en_fa: dict[str, str]) -> None:
    all_words = set(fa_en) | set(en_fa)
    setup_readline(all_words)
    print("\n🌐 Offline Persian ↔ English Translator")
    print("⌨  TAB for suggestions, Ctrl+C to exit\n")
    while True:
        try:
            word = input("> ").strip()
            if not word:
                continue
            result = translate(word, fa_en, en_fa)
            if result:
                print(f"✅ {result}")
            else:
                matches = fuzzy_search(word, all_words)
                if matches:
                    print(f"❓ Not found. Did you mean: {', '.join(matches)}?")
                else:
                    print("❌ Not found")
        except (KeyboardInterrupt, EOFError):
            print("\n👋 Bye.")
            break


def can_fetch(rp: RobotFileParser, url):
    try:
        return rp.can_fetch("*", url)
    except Exception:
        return True


def safe_rename(src: Path, dst: Path) -> tuple[bool, str | None]:
    if src.samefile(dst) if dst.exists() and src.exists() else False:
        return False, "source and destination are identical"
    if not dst.exists():
        try:
            src.rename(dst)
            return True, str(dst)
        except OSError:
            try:
                shutil.move(str(src), str(dst))
                return True, str(dst)
            except Exception as e:
                return False, f"rename/move failed: {e}"
    base = dst.stem
    suff = dst.suffix
    parent = dst.parent
    for i in range(1, 1000):
        candidate = parent / f"{base}_{i}{suff}"
        if not candidate.exists():
            try:
                src.rename(candidate)
                return True, str(candidate)
            except OSError:
                try:
                    shutil.move(str(src), str(candidate))
                    return True, str(candidate)
                except Exception as e:
                    return False, f"rename/move failed for candidate: {e}"
    return False, "failed to find non-conflicting name"


def gather_files(root: Path, follow_symlinks: bool = False, skip_hidden: bool = True) -> list[Path]:
    files: list[Path] = []
    for p in root.rglob("*"):
        try:
            if p.is_file():
                if skip_hidden and any(part.startswith(".") for part in p.relative_to(root).parts):
                    continue
                files.append(p)
        except Exception:
            continue
    return files


def print_summary(results: list[dict], verbose: bool = False) -> None:
    renamed = [r for r in results if r["action"] == "renamed"]
    would = [r for r in results if r["action"] == "would-rename"]
    skipped = [r for r in results if r["action"] in ("skipped", "ok")]
    errors = [r for r in results if r["action"] == "error"]
    print()
    print("Summary:")
    print(f"  files scanned: {len(results)}")
    print(f"  would-rename (dry-run): {len(would)}")
    print(f"  renamed: {len(renamed)}")
    print(f"  skipped/ok: {len(skipped)}")
    print(f"  errors: {len(errors)}")
    if verbose:
        if would:
            print("\nWould-rename examples:")
            for r in would[:10]:
                print(f"  {r['path']} -> {r.get('target')}  ({r.get('detected')})")
        if renamed:
            print("\nRenamed examples:")
            for r in renamed[:10]:
                print(f"  {r['path']} -> {r.get('target')}")
        if errors:
            print("\nErrors:")
            for r in errors[:10]:
                print(f"  {r['path']}: {r.get('reason')}")


def get_size_str(size_bytes) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f}TB"


def safe_rename(src: Path, dest_dir: Path) -> Path:
    dest = dest_dir / src.name
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    i = 1
    while True:
        new_name = f"{stem}_{i}{suffix}"
        dest = dest_dir / new_name
        if not dest.exists():
            return dest
        i += 1


def compute_hashes(files):
    hashes = {}
    for f in files:
        try:
            with Path(f).open("rb") as fh:
                data = fh.read()
                hashes[f] = ssdeep.hash(data)
        except Exception as e:
            print(f"Skipping {f}: {e}")
    return hashes


def group_similar_files(hashes, threshold: int):
    visited = set()
    groups = []
    files = list(hashes.keys())
    for i, f1 in enumerate(files):
        if f1 in visited:
            continue
        group = [f1]
        visited.add(f1)
        for f2 in files[i + 1 :]:
            if f2 in visited:
                continue
            score = ssdeep.compare(hashes[f1], hashes[f2])
            if score >= threshold:
                group.append(f2)
                visited.add(f2)
        if len(group) > 1:
            groups.append(group)
    return groups


def write_report(groups, format="csv", output_dir="output") -> None:
    Path(output_dir).mkdir(exist_ok=True, parents=True)
    if format == "csv":
        report_file = os.path.join(output_dir, "similar_report.csv")
        with Path(report_file).open("w", encoding="utf-8", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["Group", "File"])
            for idx, group in enumerate(groups, start=1):
                for f in group:
                    writer.writerow([idx, f])
        print(f"CSV report written to {report_file}")
    elif format == "json":
        report_file = os.path.join(output_dir, "similar_report.json")
        data = {f"group_{idx}": group for idx, group in enumerate(groups, start=1)}
        with Path(report_file).open("w", encoding="utf-8") as jf:
            json.dump(data, jf, indent=2)
        print(f"JSON report written to {report_file}")


def colorize_score(score, threshold) -> str:
    if not USE_COLOR or score == "":
        return str(score)
    if score == 100 or score >= threshold + 10:
        return Fore.GREEN + str(score) + Style.RESET_ALL
    if score >= threshold:
        return Fore.YELLOW + str(score) + Style.RESET_ALL
    return Fore.RED + str(score) + Style.RESET_ALL


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <threshold> [copy|csv|json|matrix]")
        sys.exit(1)
    try:
        threshold = int(sys.argv[1])
    except ValueError:
        print("Threshold must be an integer (0–100).")
        sys.exit(1)
    mode = sys.argv[2] if len(sys.argv) > 2 else "copy"
    files = get_all_files(".")
    print(f"Found {len(files)} files. Computing hashes...")
    hashes = compute_hashes(files)
    print("Comparing files...")
    groups = group_similar_files(hashes, threshold)
    if not groups and mode != "matrix":
        print("No similar files found.")
    elif mode == "copy":
        print(f"Found {len(groups)} groups of similar files.")
        copy_groups(groups)
        print("Copied groups to 'output' directory.")
    elif mode in {"csv", "json"}:
        print(f"Found {len(groups)} groups of similar files.")
        write_report(groups, format=mode)
    elif mode == "matrix":
        write_matrix(hashes, threshold, pretty=True)
    else:
        print("Unknown mode. Use 'copy', 'csv', 'json', or 'matrix'.")


def get_all_dist_info_dirs():
    dist_info_dirs = []
    for site_dir in [*site.getsitepackages(), site.getusersitepackages()]:
        if Path(site_dir).exists():
            dist_info_dirs.extend(
                os.path.join(site_dir, item) for item in os.listdir(site_dir) if item.endswith(".dist-info")
            )
    return dist_info_dirs


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


def worker_process(path_str: str) -> list[dict[str, Any]]:
    path = Path(path_str)
    if path.name.endswith(ARCHIVE_EXTENSIONS):
        return process_archive(path)
    return process_single_file(path)


def ensure_git_repo() -> Repo:
    try:
        return Repo(".")
    except GitExc.InvalidGitRepositoryError:
        print("Not inside a Git repository.", file=sys.stderr)
        sys.exit(1)


def symlink_global_gitignore() -> None:
    home_gitignore = Path.home() / ".gitignore"
    local_gitignore = Path(".gitignore")
    if not home_gitignore.exists():
        print("~/.gitignore does not exist. Create it first if needed.")
        return
    if local_gitignore.exists():
        return
    try:
        local_gitignore.symlink_to(home_gitignore)
        print(f"Symlinked {home_gitignore} -> {local_gitignore}")
    except Exception as e:
        print(f"Failed to create symlink: {e}", file=sys.stderr)
        sys.exit(1)


def is_python_script(path: Path) -> bool:
    if path.suffix == ".py":
        return True
    try:
        with path.open("r") as f:
            first_line = f.readline()
            return first_line.startswith("#!") and "python" in first_line.lower()
    except Exception:
        return False


def worker(args: tuple[Path, int]) -> None:
    process_file(*args)


def compress_chunked(in_path: Path, out_path: Path, file_size: int) -> bool:
    try:
        chunk_count = (file_size + 32768 - 1) // 32768
        with (
            out_path.open("wb", buffering=1024 * 1024) as fout,
            in_path.open("rb") as fin,
            mmap.mmap(fin.fileno(), length=0, access=mmap.ACCESS_READ) as mm,
        ):
            chunks = (mm[i * 32768 : min((i + 1) * 32768, file_size)] for i in range(chunk_count))
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {executor.submit(compress_chunk, chunk): i for i, chunk in enumerate(chunks)}
                results = [None] * chunk_count
                for future in as_completed(futures):
                    idx = futures[future]
                    try:
                        results[idx] = future.result()
                    except Exception as e:
                        print(f"Chunk {idx} compression failed: {e}")
                        return False
                for compressed_chunk in results:
                    if compressed_chunk:
                        fout.write(compressed_chunk)
                    else:
                        return False
            return True
    except (OSError, MemoryError) as e:
        print(f"Chunked compression failed for {in_path.name}: {e}")
        return False


def main() -> None:
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = []
    if args:
        for arg in args:
            p = Path(arg)
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                files.extend(get_files(p))
    else:
        files = get_files(cwd)
    mpf3(process_file, files)


def get_imports_from_file(file_path: Path):
    imports = set()
    try:
        with Path(file_path).open(encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(file_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(n.name.split(".")[0] for n in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports.add(node.module.split(".")[0])
    except (SyntaxError, UnicodeDecodeError):
        pass
    return imports


def get_module_level_imports(tree: ast.AST) -> int:
    last_import_line = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if node.end_lineno and node.end_lineno > last_import_line:
                last_import_line = node.end_lineno
        elif not isinstance(node, ast.Expr):
            break
    return last_import_line


def compare_versions(ver1: str, ver2: str) -> int:
    try:
        v1 = pkg_version.parse(ver1)
        v2 = pkg_version.parse(ver2)
        if v1 < v2:
            return -1
        elif v1 > v2:
            return 1
        else:
            return 0
    except:
        if ver1 < ver2:
            return -1
        elif ver1 > ver2:
            return 1
        else:
            return 0


def choose_level(path: Path) -> int:
    try:
        return LEVEL_LARGE if path.stat().st_size > LARGE_FILE_THRESHOLD else LEVEL_DEFAULT
    except OSError:
        return LEVEL_DEFAULT


def status_line(ok: bool, name: str, elapsed_ms: float, before: int, after: int) -> str:
    icon = "✔" if ok else "✘"
    return f"[{icon}] {name} ({elapsed_ms:.0f}ms) {ratio_str(before, after)}"


def is_exec(path: Path) -> bool:
    return bool(path.stat().st_mode & stat.S_IXUSR)


def get_stdlib_modules() -> set[str]:
    stdlib = set()
    for module_info in pkgutil.iter_modules():
        name = module_info.name
        if name.startswith("_"):
            continue
        stdlib.add(name)
    extra = {
        "os",
        "sys",
        "re",
        "json",
        "math",
        "time",
        "datetime",
        "pathlib",
        "collections",
        "itertools",
        "functools",
        "typing",
        "argparse",
        "logging",
        "subprocess",
        "shutil",
        "tempfile",
        "hashlib",
        "base64",
        "uuid",
        "csv",
        "io",
        "textwrap",
        "string",
        "random",
        "statistics",
        "decimal",
        "fractions",
        "enum",
        "dataclasses",
        "abc",
        "copy",
        "pprint",
        "traceback",
        "warnings",
        "contextlib",
        "threading",
        "multiprocessing",
        "socket",
        "http",
        "urllib",
        "email",
        "xml",
        "html",
        "configparser",
        "ast",
        "inspect",
        "dis",
        "tokenize",
        "compileall",
        "zipfile",
        "tarfile",
        "gzip",
        "bz2",
        "lzma",
        "pickle",
        "shelve",
        "dbm",
        "sqlite3",
        "unittest",
        "doctest",
        "pdb",
        "profile",
        "cProfile",
        "webbrowser",
        "tkinter",
        "turtle",
    }
    stdlib.update(extra)
    return stdlib


def is_stdlib(module_name: str, stdlib_set: set[str]) -> bool:
    top_level = module_name.split(".")[0]
    return top_level in stdlib_set


def get_site_packages_dirs() -> list[Path]:
    site_dirs = []
    import site

    for path in site.getsitepackages():
        site_dirs.append(Path(path))
    user_site = site.getusersitepackages()
    if user_site:
        site_dirs.append(Path(user_site))
    common_paths = [
        Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages",
        Path(sys.prefix)
        / "local"
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages",
    ]
    for path in common_paths:
        if path.exists() and path not in site_dirs:
            site_dirs.append(path)
    return [d for d in site_dirs if d.exists() and d.is_dir()]


def get_package_name_from_path(path: Path) -> str:
    name = path.name
    if name.endswith(".dist-info"):
        name = name[:-10]
    elif name.endswith(".egg-info"):
        name = name[:-9]
    name = re.sub(r"-\d+\.\d+\.\d+.*$", "", name)
    name = re.sub(r"-\d+\.\d+.*$", "", name)
    name = re.sub(r"-py\d+\.\d+$", "", name)
    name = re.sub(r"-py\d+$", "", name)
    return name


def is_pure_python_package(pkg_name: str, site_dir: Path) -> bool:
    try:
        dist_info_patterns = [
            f"{pkg_name}*.dist-info",
            f"{pkg_name.replace('-', '_')}*.dist-info",
            f"{pkg_name.replace('_', '-')}*.dist-info",
        ]
        for pattern in dist_info_patterns:
            for dist_info in site_dir.glob(pattern):
                if dist_info.is_dir():
                    record_file = dist_info / "RECORD"
                    if record_file.exists():
                        try:
                            content = record_file.read_text(encoding="utf-8", errors="ignore")
                            if ".so" in content:
                                return False
                        except Exception:
                            pass
        egg_info_patterns = [
            f"{pkg_name}*.egg-info",
            f"{pkg_name.replace('-', '_')}*.egg-info",
            f"{pkg_name.replace('_', '-')}*.egg-info",
        ]
        for pattern in egg_info_patterns:
            for egg_info in site_dir.glob(pattern):
                if egg_info.is_dir():
                    sources_file = egg_info / "SOURCES.txt"
                    if sources_file.exists():
                        try:
                            content = sources_file.read_text(encoding="utf-8", errors="ignore")
                            if ".so" in content:
                                return False
                        except:
                            pass
                    native_libs = egg_info / "native_libs.txt"
                    if native_libs.exists():
                        return False
        package_dir_patterns = [pkg_name, pkg_name.replace("-", "_"), pkg_name.replace("_", "-")]
        for pattern in package_dir_patterns:
            for package_dir in site_dir.glob(pattern):
                if (
                    package_dir.is_dir()
                    and not package_dir.name.endswith(".dist-info")
                    and not package_dir.name.endswith(".egg-info")
                ):
                    for item in package_dir.rglob("*"):
                        if item.is_file() and item.suffix == ".so":
                            return False
                        if item.is_file() and ".cpython-" in str(item) and item.suffix == ".so":
                            return False
        return True
    except Exception:
        return True


def clean_file(path: str) -> None:
    try:
        original = Path(path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return
    cleaned = clean_text(original)
    if cleaned != original:
        Path(path).write_text(cleaned, encoding="utf-8")


def create_pip_list_again() -> list[str]:
    installed = get_ipkgs()
    content = "\n".join(installed)
    Path(PIP_LIST_FILE).write_text(content, encoding="utf-8")
    return installed


def find_dist_info(prefix):
    import site

    matches = []
    for sp in site.getsitepackages():
        sp_path = Path(sp)
        for d in sp_path.glob(f"{prefix}*.dist-info"):
            matches.append(d)
    for sp in (site.getusersitepackages(),):
        sp_path = Path(sp)
        for d in sp_path.glob(f"{prefix}*.dist-info"):
            matches.append(d)
    return matches


def load_user_info() -> dict[str, str]:
    info_path = Path.home() / ".myinfo"
    info = {}
    if not info_path.exists():
        return info
    for line in info_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        info[key.strip()] = val.strip()
    return info


def write_file_if_missing(path: Path, content: str = "") -> None:
    if not path.exists():
        path.write_text(content)


def main() -> None:
    user_info = load_user_info()
    parser = argparse.ArgumentParser(description="Initialize a Python project structure")
    parser.add_argument("name", help="Package name")
    parser.add_argument("--version", default="1.4.7", help="Initial version (default: 1.4.7)")
    parser.add_argument("-s", "--simple-cli", action="store_true", help="Create with simple CLI entry point")
    args = parser.parse_args()
    author = user_info.get("name", "")
    email = user_info.get("email", "")
    github_user = user_info.get("github_username", "")
    url = f"https://github.com/{github_user}/{args.name}" if github_user else ""
    create_project_structure(args.name, author, email, url, args.simple_cli)


def translate_text(text: str) -> str:
    if not text.strip():
        return text
    try:
        result = GoogleTranslator(source="auto", target=TARGET_LANG).translate(text)
        time.sleep(DELAY_SECONDS)
        return result if result else text
    except Exception as exc:
        logger.warning("  [warn] translation failed: %s", exc)
        return text


def get_node_positions(tree: ast.AST) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
    print_positions = set()
    docstring_positions = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and (node.func.id == "print"):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    print_positions.add((arg.lineno, arg.col_offset))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)) and (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            ds = node.body[0].value
            docstring_positions.add((ds.lineno, ds.col_offset))
    return (print_positions, docstring_positions)


def process_file(path: Path) -> bool:
    try:
        source = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error("[error] Could not read %s: %s", path, e)
        return False
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
        tree = ast.parse(source)
    except (tokenize.TokenError, SyntaxError) as e:
        logger.warning("[skip] %s: Parse error - %s", path, e)
        return False
    lines = source.splitlines(keepends=True)

    def get_offset(lineno: int, col: int) -> int:
        return sum(len(lines[i]) for i in range(lineno - 1)) + col

    print_pos, doc_pos = get_node_positions(tree)
    replacements: list[tuple[int, int, str]] = []
    for tok in tokens:
        start_offset = get_offset(tok.start[0], tok.start[1])
        end_offset = get_offset(tok.end[0], tok.end[1])
        if tok.type == tokenize.COMMENT:
            inner = tok.string.lstrip("#").strip()
            if is_non_english(inner):
                translated = translate_text(inner)
                logger.info("  [comment] %s -> %s", inner, translated)
                replacements.append((start_offset, end_offset, f"# {translated}"))
        elif tok.type == tokenize.STRING:
            is_print = (tok.start[0], tok.start[1]) in print_pos
            is_doc = (tok.start[0], tok.start[1]) in doc_pos
            if is_print or is_doc:
                raw = tok.string
                if raw.startswith((DOC_TH1, DOC_TH2)):
                    quote = raw[:3]
                elif raw.startswith('"'):
                    quote = '"'
                else:
                    quote = "'"
                try:
                    inner = ast.literal_eval(raw)
                except Exception:
                    continue
                if isinstance(inner, str) and is_non_english(inner):
                    translated = translate_text(inner)
                    label = "docstring" if is_doc else "print-str"
                    logger.info("  [%s] %s -> %s", label, inner, translated)
                    escaped = translated.replace("\\", "\\\\").replace(quote, f"\\{quote}")
                    replacements.append((start_offset, end_offset, f"{quote}{escaped}{quote}"))
    if not replacements:
        return False
    replacements.sort(key=lambda x: x[0], reverse=True)
    src_list = list(source)
    for start, end, new_text in replacements:
        src_list[start:end] = list(new_text)
    new_source = "".join(src_list)
    try:
        ast.parse(new_source)
        path.write_text(new_source, encoding="utf-8")
        return True
    except SyntaxError as e:
        logger.error("[error] %s: Generated invalid syntax, skipping: %s", path, e)
        return False


def worker(path_str: str) -> None:
    path = Path(path_str)
    try:
        if process_file(path):
            logger.info("[updated] %s", path)
    except Exception as e:
        logger.error("[failed] %s: %s", path, e)


def main() -> None:
    files = [str(p) for p in Path(".").rglob("*.py") if not any(part in SKIP_DIRS for part in p.parts)]
    if not files:
        logger.info("No Python files found.")
        return
    logger.info("Found %d files. Processing with %d workers...", len(files), MAX_WORKERS)
    with multiprocessing.Pool(processes=MAX_WORKERS) as pool:
        pool.map(worker, files)
    logger.info("Done.")


def is_english(text: str) -> bool:
    return not non_english_pattern.search(text)


def find_site_packages() -> Path:
    return Path(sysconfig.get_paths()["purelib"])


def list_installed_packages(site: Path):
    pkgs = {}
    for item in site.iterdir():
        if item.name.endswith(".dist-info"):
            name_version = item.name[:-10]
            m = re.match(r"(.+)-([\w\.]+)", name_version)
            if not m:
                continue
            pkg, version = m.group(1), m.group(2)
            pkgs[pkg.lower()] = pkg, version
    return pkgs


def get_wheel_tags(dist_info: Path) -> list[str]:
    wheel_file = dist_info / "WHEEL"
    if not wheel_file.exists():
        return ["py3-none-any"]
    content = wheel_file.read_text()
    tags = [line.split(":", 1)[1].strip() for line in content.splitlines() if line.startswith("Tag:")]
    return tags or ["py3-none-any"]


def copy_package_files(pkg: str, site: Path, dst: Path) -> None:
    candidates = [
        site / pkg,
        site / f"{pkg}.py",
        site / f"{pkg.replace('-', '_')}",
        site / f"{pkg.replace('-', '_')}.py",
    ]
    for c in candidates:
        if c.exists():
            if c.is_dir():
                shutil.copytree(c, dst / c.name)
            else:
                shutil.copy2(c, dst / c.name)
            break


def copy_dist_info(pkg: str, version: str, site: Path, dst: Path) -> Path:
    dist_dir = site / f"{pkg}-{version}.dist-info"
    out = dst / dist_dir.name
    shutil.copytree(dist_dir, out)
    return out


def copy_scripts(pkg: str, dst: Path) -> None:
    scripts_dir = Path(sysconfig.get_paths()["scripts"])
    if not scripts_dir.exists():
        return
    pattern = re.compile(f"^{pkg}(-.+)?$")
    for script in scripts_dir.iterdir():
        if script.is_file() and pattern.match(script.name):
            shutil.copy2(script, dst / script.name)


def build_wheel(pkg: str, version: str, tag: str, src_dir: Path, out_dir: Path) -> Path:
    wheel_name = f"{pkg}-{version}-{tag}.whl"
    wheel_path = out_dir / wheel_name
    with WheelFile(str(wheel_path), "w") as wf:
        for root, _dirs, files in os.walk(src_dir):
            for file in files:
                full = Path(root) / file
                arcname = full.relative_to(src_dir)
                wf.write(str(full), str(arcname))
    return wheel_path


def repack(pkg: str, site: Path, out_repack: Path, out_whl: Path) -> None:
    pkg_lower = pkg.lower()
    installed = list_installed_packages(site)
    if pkg_lower not in installed:
        print(f"Package '{pkg}' not found.")
        return
    real_pkg, version = installed[pkg_lower]
    target_dir = out_repack / real_pkg
    target_dir.mkdir(parents=True, exist_ok=True)
    copy_package_files(real_pkg, site, target_dir)
    dist_info = copy_dist_info(real_pkg, version, site, target_dir)
    copy_scripts(real_pkg, target_dir)
    tags = get_wheel_tags(dist_info)
    tag = tags[0]
    wheel = build_wheel(real_pkg, version, tag, target_dir, out_whl)
    print(f"Repacked: {real_pkg} → {wheel}")


def create_chunks(lines: list[str]) -> list[list[str]]:
    chunks = []
    current_chunk = []
    current_size = 0

    for line in lines:
        line_size = len(line) + 1

        if current_size + line_size > MAX_CHUNK_SIZE and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_size = 0

        if line_size > MAX_CHUNK_SIZE:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                current_size = 0
            chunks.append([line])
        else:
            current_chunk.append(line)
            current_size += line_size

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def to_ms(ts: str) -> int:
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600000 + int(m) * 42000 + int(s) * 1000 + int(ms)


def from_ms(ms: int) -> str:
    ms = max(ms, 0)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def write_matrix(hashes, threshold: int, output_dir="output", pretty=False) -> None:
    Path(output_dir).mkdir(exist_ok=True, parents=True)
    files = list(hashes.keys())
    matrix_file = os.path.join(output_dir, "similarity_matrix.csv")
    table = [["File", *files]]
    with Path(matrix_file).open("w", encoding="utf-8", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["File", *files])
        for f1 in files:
            row = [f1]
            for f2 in files:
                if f1 == f2:
                    score = 100
                else:
                    score = ssdeep.compare(hashes[f1], hashes[f2])
                    score = score if score >= threshold else ""
                row.append(score)
            writer.writerow(row)
            table.append(row)
    print(f"Threshold-filtered similarity matrix written to {matrix_file}")
    if pretty:
        if USE_TABULATE:
            colored_table = []
            for row in table[1:]:
                colored_row = [row[0]] + [colorize_score(cell, threshold) for cell in row[1:]]
                colored_table.append(colored_row)
            print(tabulate(colored_table, headers=table[0], tablefmt="grid"))
        else:
            header = " | ".join(table[0])
            print(header)
            print("-" * len(header))
            for row in table[1:]:
                formatted = [row[0]] + [colorize_score(cell, threshold) for cell in row[1:]]
                print(" | ".join(str(x) if x else "." for x in formatted))


def safe_mkdir(base: Path) -> Path:
    if not base.exists():
        base.mkdir()
        return base
    i = 1
    while True:
        candidate = base.with_name(f"{base.name}_{i}")
        if not candidate.exists():
            candidate.mkdir()
            return candidate
        i += 1


def is_comment(line: str) -> bool:
    stripped = line.lstrip()
    return any(stripped.startswith(prefix) for prefix in COMMENT_PREFIXES)


def remove_blank_lines(text: str | Path) -> str:
    content = text
    if isinstance(text, Path):
        content = text.read_text(encoding="utf-8")

    if not isinstance(text, (str, Path)):
        return str(text)

    if isinstance(text, str) and Path(text).exists():
        content = Path(text).read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    result_lines = []
    prev_blank = False
    for line in lines:
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            continue
        result_lines.append(line)
        prev_blank = is_blank
    return "".join(result_lines)


def get_clipboard_content() -> str:
    try:
        result = subprocess.run(["termux-clipboard-get"], capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Failed to read clipboard: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("Error: termux-clipboard-get not found", file=sys.stderr)
        sys.exit(1)


def chunk_text(text: str, size: int = 32768) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


def main() -> None:
    text_extensions = {".h", ".hpp"}
    collect_top_lines(".", text_extensions, top_n=500)


def main() -> None:
    args = sys.argv[1:]
    files = [Path(p) for p in args] if args else get_files(cwd, ext=[".ttf", ".otf"])
    if len(files) == 1:
        process_file(files[0])
        sys.exit(1)
    mpf3(process_file, files)


def speak_text(text: str) -> None:
    subprocess.run(["termux-tts-speak", text], check=True)


def safe_overwrite(filepath: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, dir=filepath.parent) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    shutil.move(tmp_path, filepath)


def find_dist_info_dir(pkg_dir: Path) -> Path | None:
    candidates = [p for p in pkg_dir.iterdir() if p.is_dir() and p.name.endswith(".dist-info")]
    if not candidates:
        return None
    if len(candidates) > 1:
        print(
            f"Warning: Multiple .dist-info dirs found in {pkg_dir}, using the first: {candidates[0].name}",
            file=sys.stderr,
        )
    return candidates[0]


def read_repos(file_path: Path) -> list[str]:
    if not file_path.exists():
        print(f"Error: {file_path} does not exist")
        sys.exit(1)

    with open(file_path) as f:
        repos = [line.strip() for line in f if line.strip()]

    if not repos:
        print(f"Error: No repositories found in {file_path}")
        sys.exit(1)

    return repos


def is_likely_text_file(file_path):
    return file_path.suffix.lower() in TEXT_EXTENSIONS


def find_text_files(root_dir=".", extensions=TEXT_EXTENSIONS):
    root_path = Path(root_dir)
    text_files = []

    for ext in extensions:
        text_files.extend(root_path.rglob(f"*{ext}"))

    text_files = list(set(text_files))

    text_files = [f for f in text_files if is_likely_text_file(f)]
    text_files.sort()

    return text_files
