import os
import subprocess
from collections import deque
from multiprocessing import Pool


def process_file(filename) -> None:
    subprocess.run(["pip", "install", filename], check=True)


if __name__ == "__main__":
    files = [fn for fn in os.listdir(".") if fn.endswith(".whl")]
    with Pool(8) as pool:
        pending_tasks = deque(pool.imap_unordered(process_file, files))
        while pending_tasks:
            try:
                pending_tasks[0].get(timeout=1)
                pending_tasks.popleft()
            except Exception as e:
                print(f"Error processing file: {e}")
