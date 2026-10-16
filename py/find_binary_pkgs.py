from pathlib import Path


def have_so_file(folder_path: Path) -> bool:
    return any(file_path.is_file() and file_path.suffix == ".so" for file_path in folder_path.rglob("*"))


def main() -> None:
    not_pure = []
    site_dir = Path("/data/data/com.termux/files/usr/lib/python3.12/site-packages")
    for path in site_dir.glob("*"):
        if path.is_dir() and not "dist-info" in path.name and have_so_file(path):
            print(path.name)
            not_pure.append(path.name)
    outfile = Path("/sdcard/notpure")
    outfile.write_text("\n".join(not_pure), encoding="utf-8")
    print(f"{outfile} created.")


if __name__ == "__main__":
    main()
