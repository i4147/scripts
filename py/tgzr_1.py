import multiprocessing
import shutil
import tarfile
from pathlib import Path

_WORKERS = 8


def _remove_item(path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def remove_items_fast(items):
    item_list = list(items)
    if not item_list:
        return
    with multiprocessing.Pool(processes=_WORKERS) as pool:
        async_results = [pool.apply_async(_remove_item, (item,)) for item in item_list]
        for result in async_results:
            result.get()


def compress_and_cleanup(root=Path()):
    root = root.resolve()
    archive_name = f"{root.name}.tar.gz"
    archive_path = root.parent / archive_name
    print(f"Creating archive: {archive_path}")
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(root, arcname=root.name)
    print("Archive created. Removing original files...")
    items = [item for item in root.iterdir() if item.resolve() != archive_path]
    remove_items_fast(items)
    print("Cleanup complete.")


if __name__ == "__main__":
    compress_and_cleanup()
