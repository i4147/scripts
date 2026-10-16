import sqlite3
from pathlib import Path


def get_current_folder_name():
    return Path.cwd().name


def folder_exists_in_db(cursor, folder_name):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (folder_name,))
    return cursor.fetchone() is not None


def create_folder_table(cursor, folder_name):
    cursor.execute(
        f'CREATE TABLE IF NOT EXISTS "{
            folder_name
        }" (id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL, file_contents TEXT)'
    )


def read_file_contents(path):
    encodings = ["utf-8", "latin-1", "cp1252", "iso-8859-1"]
    for encoding in encodings:
        try:
            return path.read_text(encoding=encoding)[: 1024 * 1024]
        except (UnicodeDecodeError, UnicodeError, PermissionError):
            continue
        except Exception as e:
            return f"[Error reading file: {e!s}]"
    return "[Binary file content not stored]"


def get_files_in_current_dir():
    current_dir = Path.cwd()
    files = []
    for item in current_dir.iterdir():
        if item.is_file():
            print(f"  Reading: {item.name}")
            files.append({"filename": item.name, "contents": read_file_contents(item)})
    return files


def insert_files(cursor, folder_name, files):
    cursor.executemany(
        f'INSERT INTO "{folder_name}" (filename, file_contents) VALUES (?, ?)',
        [(f["filename"], f["contents"]) for f in files],
    )


def main():
    db_path = Path("/sdcard/pkg.db")
    folder_name = get_current_folder_name()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        if folder_exists_in_db(cursor, folder_name):
            folder_name = folder_name + "_new"
        create_folder_table(cursor, folder_name)
        files = get_files_in_current_dir()
        if not files:
            print("No files found in current directory!")
        else:
            insert_files(cursor, folder_name, files)
            conn.commit()


if __name__ == "__main__":
    raise SystemExit(main())
