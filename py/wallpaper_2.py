import argparse
import os
import pathlib
import random
import time
import toml


def get_args():
    parser = argparse.ArgumentParser("wallpaper for dwm")
    parser.add_argument("--cfg", "-c", type=str, default="./wallpaper.toml")
    parser.add_argument("--type", type=str, choices=["all", "image", "vidio", "page"], default="both")
    parser.add_argument("--random", action="store_true")
    parser.add_argument("--path", type=str, default=None)
    return parser.parse_args()


def get_type(ext) -> int:
    if ext in {"mp4", "mkv", "avi"}:
        return 1
    if ext in {"png", "jpg"}:
        return 2
    if ext in {"html", "htm"}:
        return 3
    return 0


def set_wallpaper(cfg) -> None:
    os.system("killall xwinwrap")
    time.sleep(0.3)
    file_list = os.listdir(cfg.dir)
    for _ in range(10):
        chosen_file = random.choice(file_list)
        target_type = get_type(os.path.splitext(chosen_file)[-1])
        if target_type:
            break
    assert target_type
    if target_type == 1:
        os.system(f"xwinwrap -d -ov -fs -- mpv -wid WID {chosen_file}")


if __name__ == "__main__":
    args = get_args()
    with pathlib.Path(args.cfg).open(encoding="utf-8") as f:
        cfg = toml.load(f)
