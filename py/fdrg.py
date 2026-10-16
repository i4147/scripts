import argparse
import contextlib
import os
import pathlib
import tarfile
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue

pause_event = threading.Event()
pause_event.set()
results_queue = Queue()


def setup_keyboard_listener() -> bool:
    try:
        import keyboard

        def on_key_press(event) -> None:
            if event.name in {"space", "p"}:
                if pause_event.is_set():
                    pause_event.clear()
                    print("\n[PAUSED] Press Space or 'c' to continue...")
            elif event.name == "c" and not pause_event.is_set():
                pause_event.set()
                print("\n[RESUMED] Searching...")

        keyboard.on_press(on_key_press)
        return True
    except ImportError:
        print("Warning: 'keyboard' module not installed. Pause functionality disabled.")
        print("Install with: pip install keyboard")
        return False


def search_in_file(file_path, search_string, search_content=False):
    results = []
    pause_event.wait()
    if not search_content:
        if search_string.lower() in pathlib.Path(file_path).name.lower():
            results.append((file_path, None))
    else:
        try:
            with pathlib.Path(file_path).open(encoding="utf-8", errors="ignore") as f:
                for line_num, line in enumerate(f, 1):
                    pause_event.wait()
                    if search_string in line:
                        results.append((file_path, line_num))
        except Exception:
            pass
    return results


def extract_and_search_archive(
    archive_path,
    search_string,
    search_content=False,
):
    results = []
    archive_type = None
    if archive_path.endswith((".zip", ".whl", ".apk")):
        archive_type = "zip"
    elif archive_path.endswith((
        ".tar.gz",
        ".tar.bz2",
        ".tar.xz",
        ".tar.zst",
        ".tar",
    )):
        archive_type = "tar"
    try:
        if archive_type == "zip":
            with zipfile.ZipFile(archive_path, "r") as zf:
                for member in zf.namelist():
                    pause_event.wait()
                    if not search_content:
                        if search_string.lower() in member.lower():
                            results.append((
                                f"{archive_path}::{member}",
                                None,
                            ))
                    else:
                        try:
                            content = zf.read(member).decode(
                                "utf-8",
                                errors="ignore",
                            )
                            for (
                                line_num,
                                line,
                            ) in enumerate(
                                content.split("\n"),
                                1,
                            ):
                                if search_string in line:
                                    results.append((
                                        f"{archive_path}::{member}",
                                        line_num,
                                    ))
                        except:
                            pass
        elif archive_type == "tar":
            with tarfile.open(archive_path, "r:*") as tf:
                for member in tf.getmembers():
                    pause_event.wait()
                    if not search_content:
                        if search_string.lower() in member.name.lower():
                            results.append((
                                f"{archive_path}::{member.name}",
                                None,
                            ))
                    elif member.isfile():
                        try:
                            f = tf.extractfile(member)
                            if f:
                                content = f.read().decode(
                                    "utf-8",
                                    errors="ignore",
                                )
                                for (
                                    line_num,
                                    line,
                                ) in enumerate(
                                    content.split("\n"),
                                    1,
                                ):
                                    if search_string in line:
                                        results.append((
                                            f"{archive_path}::{member.name}",
                                            line_num,
                                        ))
                        except:
                            pass
    except Exception:
        pass
    return results


def process_file(file_path, search_string, search_content: bool = False):
    results = []
    archive_extensions = (
        ".tar.gz",
        ".tar",
        ".tar.xz",
        ".tar.zst",
        ".tar.bz2",
        ".zip",
        ".whl",
        ".apk",
    )
    if file_path.endswith(archive_extensions):
        results = extract_and_search_archive(
            file_path,
            search_string,
            search_content,
        )
    else:
        results = search_in_file(
            file_path,
            search_string,
            search_content,
        )
    for result in results:
        report_result(result[0], result[1])
    return results


def report_result(file_path, line_num=None) -> None:
    if line_num:
        print(f"[FOUND] {file_path} (Line: {line_num})")
    else:
        print(f"[FOUND] {file_path}")
    results_queue.put((file_path, line_num))


def save_results(output_dir, search_content) -> None:
    if not pathlib.Path(output_dir).exists():
        pathlib.Path(output_dir).mkdir(parents=True)
    output_file = os.path.join(output_dir, "search_results.txt")
    results = []
    while not results_queue.empty():
        results.append(results_queue.get())
    with pathlib.Path(output_file).open("w", encoding="utf-8") as f:
        f.write("Search Results\n")
        f.write(f"{'=' * 80}\n\n")
        for file_path, line_num in results:
            if search_content and line_num:
                f.write(f"{file_path} (Line: {line_num})\n")
            else:
                f.write(f"{file_path}\n")
    print(f"\n[INFO] Results saved to: {output_file}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recursively search for strings in filenames or file contents, including compressed archives"
    )
    parser.add_argument(
        "search_string",
        help="String to search for",
    )
    parser.add_argument(
        "-c",
        "--content",
        action="store_true",
        help="Search inside file contents instead of filenames",
    )
    parser.add_argument(
        "-d",
        "--directory",
        default=".",
        help="Directory to search (default: current directory)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="output",
        help="Output directory for results (default: output)",
    )
    args = parser.parse_args()
    keyboard_enabled = setup_keyboard_listener()
    print(f"[INFO] Searching for: '{args.search_string}'")
    print(f"[INFO] Search mode: {'Content' if args.content else 'Filename'}")
    print(f"[INFO] Directory: {pathlib.Path(args.directory).resolve()}")
    if keyboard_enabled:
        print("[INFO] Press Space or 'p' to pause, 'c' to continue")
    print(f"{'=' * 80}\n")
    files_to_search = []
    for root, _dirs, files in os.walk(args.directory):
        for file in files:
            if ".git" in str(os.path.join(root, file)):
                continue
            if "dist" in str(os.path.join(root, file)):
                continue
            if "output" in str(os.path.join(root, file)):
                continue
            files_to_search.append(os.path.join(root, file))
    print(f"[INFO] Found {len(files_to_search)} files to search\n")
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(
                process_file,
                file_path,
                args.search_string,
                args.content,
            ): file_path
            for file_path in files_to_search
        }
        for future in as_completed(futures):
            with contextlib.suppress(Exception):
                future.result()
    print(f"[INFO] Total results found: {results_queue.qsize()}")


if __name__ == "__main__":
    main()
