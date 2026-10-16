from collections import defaultdict
from pathlib import Path

import cffi
from dh import get_files

ffi = cffi.FFI()
ffi.cdef("""
    char* hash_file_c(const char* path_cstr);
    void free_hash_string(char* str);
""")
lib_name = "/data/data/com.termux/files/usr/lib/python3.12/site-packages/libhasher.so"
hasher_lib = ffi.dlopen(lib_name)


def calculate_file_hash(filepath: str):
    if not Path(filepath).exists():
        print(f"Error: File not found at {filepath}")
        return None
    c_filepath = ffi.new("char[]", filepath.encode("utf-8"))
    c_hash_ptr = hasher_lib.hash_file_c(c_filepath)
    if c_hash_ptr == ffi.NULL:
        print(f"Error: C function returned NULL for file: {filepath}")
        return None
    try:
        return ffi.string(c_hash_ptr).decode("utf-8")
    finally:
        hasher_lib.free_hash_string(c_hash_ptr)


if __name__ == "__main__":
    cwd = Path.cwd()
    files = get_files(cwd)
    f_by_h = {}
    size_groups = defaultdict(list)
    removed = 0
    for f in files:
        if f.is_file() and not f.is_symlink():
            try:
                size = f.stat().st_size
                size_groups[size].append(f)
            except OSError as e:
                print(f"Error accessing {f}: {e}")
    files_to_hash = []
    for size, files in size_groups.items():
        if len(files) > 1:
            files_to_hash.extend(files)
    for filepath in files_to_hash:
        h = calculate_file_hash(str(filepath))
        f_by_h.setdefault(h, []).append(filepath)
    for _h, paths in f_by_h.items():
        if len(paths) > 1:
            print(f"dups with hash :{_h}\n")
            for path in paths[1:]:
                print(f"{path} removed")
                path.unlink()
                removed += 1
    if removed:
        print(f"{removed} files removed.")
    else:
        print("no dups found")
