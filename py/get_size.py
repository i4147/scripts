import os
import pathlib
import shutil


def get_size(name: str) -> float:
    fd_path = os.path.join(path, name)
    size = 0
    for root, _dirs, files in os.walk(fd_path):
        for file in files:
            file_path = os.path.join(root, file)
            size += pathlib.Path(file_path).stat().st_size
    size = round(size / 1024**2, 2)
    size_text = f"{size} MB"
    dis = " " * (shutil.get_terminal_size().columns - len(name) - len(size_text))
    if size > 0:
        size_text = f"\033[0;92m{size} MB\033[0;0m"
    print(f"{name}{dis}{size_text}")
    return size


path = "/data/data/ru.iiec.pydroid3/files/arm-linux-androideabi/lib/python3.9/site-packages"
total_size = sum(get_size(fd) for fd in os.listdir(path))
print(f"\nTổng: {total_size} MB")
