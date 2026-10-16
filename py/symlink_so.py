from pathlib import Path

if __name__ == "__main__":
    libdir: Path = Path.home() / ".local" / "lib"
    for path in libdir.glob("*"):
        if path.is_symlink():
            continue
        if ".so" in path.name:
            indx = path.name.index(".so")
            symlink_path1 = path.with_name(path.name[: indx - 1] + ".so.0")
            symlink_path2 = path.with_name(path.name[: indx - 1] + ".so.1")
            if not symlink_path1.exists():
                symlink_path1.symlink_to(path)
                print(f"Created: {symlink_path1.name} -> {path.name}")
            if not symlink_path2.exists():
                symlink_path2.symlink_to(path)
                print(f"Created: {symlink_path2.name} -> {path.name}")
    print("done")
