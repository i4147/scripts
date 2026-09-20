import sys
import packaging

with open("sysmodules.txt", "w") as f1:
    for item in sys.modules:
        f1.write(item)
        f1.write("\n")
with open("sys_builtin_module_names.txt", "w") as f2:
    for k in sys.builtin_module_names:
        f2.write(k)
        f2.write("\n")
with open("sys_stdlib_module_names.txt", "w") as f3:
    for z in sys.stdlib_module_names:
        f3.write(z)
        f3.write("\n")
