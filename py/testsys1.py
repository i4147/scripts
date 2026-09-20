import pathlib
import sys

with pathlib.Path("sysmodules.txt").open("w", encoding="utf-8") as f1:
    for item in sys.modules:
        f1.write(item)
        f1.write("\n")
with pathlib.Path("sys_builtin_module_names.txt").open("w", encoding="utf-8") as f2:
    for k in sys.builtin_module_names:
        f2.write(k)
        f2.write("\n")
with pathlib.Path("sys_stdlib_module_names.txt").open("w", encoding="utf-8") as f3:
    for z in sys.stdlib_module_names:
        f3.write(z)
        f3.write("\n")
