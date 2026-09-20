import os
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from dh import is_valid_archive

TARGET_FILES = {"METADATA", "PKGINFO", "PKG-INFO"}
PREFIX = "Requires-Dist:"
LOG_FILE = "/sdcard/reqz.txt"
removed_lines_accumulator = []


def clean_text(text: str) -> tuple[str, list[str]]:
    lines = text.splitlines()
    cleaned = []
    removed = []
    for line in lines:
        if line.startswith(PREFIX):
            removed.append(line)
        else:
            cleaned.append(line)
    final_text = "\n".join(cleaned) + ("\n" if text.endswith("\n") else "")
    return final_text, removed


def clean_file(path: str) -> None:
    try:
        original = Path(path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return
    cleaned, removed = clean_text(original)
    if removed:
        removed_lines_accumulator.extend(removed)
        Path(path).write_text(cleaned, encoding="utf-8")


def process_zip(path: str) -> None:
    tmp = tempfile.mktemp(suffix=".zip")
    with zipfile.ZipFile(path, "r") as zin, zipfile.ZipFile(tmp, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            base = Path(item.filename).name
            if base in TARGET_FILES:
                try:
                    text = data.decode("utf-8", errors="ignore")
                    cleaned, removed = clean_text(text)
                    if removed:
                        removed_lines_accumulator.extend(removed)
                    data = cleaned.encode("utf-8")
                except Exception:
                    pass
            zout.writestr(item, data)
    shutil.move(tmp, path)


def process_tar(path: str) -> None:
    tmp_dir = tempfile.mkdtemp()
    tmp_tar = tempfile.mktemp(suffix=".tar.gz")
    with tarfile.open(path, "r:*") as tar:
        tar.extractall(tmp_dir, filter="data")
    for root, _, files in os.walk(tmp_dir):
        for name in files:
            if name in TARGET_FILES:
                clean_file(os.path.join(root, name))
    with tarfile.open(tmp_tar, "w:gz") as tar:
        tar.add(tmp_dir, arcname="")
    shutil.move(tmp_tar, path)
    shutil.rmtree(tmp_dir)


def dispatch_archive(path: str | Path) -> None:
    if not is_valid_archive(path):
        print(f"{path} is not valid archive")
        return
    name = path.lower()
    if name.endswith(".whl"):
        print(f"processing ... {path}")
        process_zip(path)
    elif name.endswith((".tar.gz", ".tgz", ".tar")):
        process_tar(path)


def main() -> None:
    for root, _, files in os.walk("."):
        for filename in files:
            full_path = os.path.join(root, filename)
            if filename in TARGET_FILES or filename.endswith(".metadata"):
                clean_file(full_path)
            elif filename.lower().endswith((".zip", ".whl", ".tar.gz", ".tgz", ".tar")):
                dispatch_archive(full_path)
    if removed_lines_accumulator:
        try:
            with Path(LOG_FILE).open("a", encoding="utf-8") as f:
                f.writelines(line + "\n" for line in removed_lines_accumulator)
            print(f"--- Saved {len(removed_lines_accumulator)} lines to {LOG_FILE} ---")
        except PermissionError:
            pass
        print("\nRemoved Lines:")
        print("-" * 20)
        for line in removed_lines_accumulator:
            print(line)
        print("-" * 20)
    else:
        print("No matching lines were found or removed.")


if __name__ == "__main__":
    main()
