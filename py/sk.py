import os
import site
import sys

original_sys_path = sys.path[:]
known_paths = set()
for path in ("/data/data/com.termux/files/usr/lib/python3.12/site-packages",):
    site.addsitedir(path, known_paths=known_paths)
system_paths = {os.path.normcase(path) for path in sys.path[len(original_sys_path) :]}
sys.path = original_sys_path
for path in [
    "/data/data/ru.iiec.pydroid3/cache/pip-build-env-rpsdhrwe/overlay/lib/python3.13/site-packages",
    "/data/data/com.termux/files/home/.local/lib/python3.12/site-packages",
]:
    assert path not in sys.path
    site.addsitedir(path)
for path in system_paths:
    site.addsitedir(path)
