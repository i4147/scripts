import base64
import csv
import hashlib
from pathlib import Path

HASH_ALGO = "sha256"
ALLOWED = {
    "METADATA",
    "WHEEL",
    "RECORD",
    "top_level.txt",
    "entry_points.txt",
}


def hash_file(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    digest = base64.urlsafe_b64encode(h.digest()).decode().rstrip("=")
    return (
        f"{HASH_ALGO}={digest}",
        path.stat().st_size,
    )


def process_record(record_path: Path) -> None:
    site_packages = record_path.parent.parent
    dist_info = record_path.parent
    dist_info_name = dist_info.name
    print(f"processing {dist_info_name}")
    new_rows = []
    with record_path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            rel_path = row[0]
            if rel_path.endswith(".pyc"):
                continue
            path_parts = Path(rel_path).parts
            if path_parts and path_parts[0] == dist_info_name:
                filename = Path(rel_path).name
                if filename not in ALLOWED:
                    continue
            abs_path = site_packages / rel_path
            if abs_path.resolve() == record_path.resolve():
                new_rows.append([rel_path, "", ""])
                continue
            if abs_path.exists() and abs_path.is_file():
                hashval, size = hash_file(abs_path)
                new_rows.append([rel_path, hashval, str(size)])
            else:
                new_rows.append([rel_path, "", ""])
    tmp = record_path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(new_rows)
    tmp.replace(record_path)
    print(f"{record_path} updated")


def fix_site_packages(site_packages: Path) -> None:
    for record in site_packages.rglob("*.dist-info/RECORD"):
        process_record(record)


if __name__ == "__main__":
    dir = "/data/data/com.termux/files/usr/lib/python3.12/site-packages"
    fix_site_packages(Path(dir))
