import os

from dh import run_command
from termcolor import cprint

cwd = "/data/data/com.termux/files/usr/lib/python3.12/site-packages"
for k in os.listdir(cwd):
    if k.endswith(".zip"):
        pkg = k.replace(".zip", "")
        cmd = f"uzp {pkg}"
        ret, txt, err = run_command(cmd)
        if ret == 0:
            print(txt)
        else:
            cprint(f"{pkg} err", "cyan")
