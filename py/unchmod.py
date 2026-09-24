import os, glob, stat

for path in glob.glob("*.py"):
    mode = os.stat(path).st_mode
    new_mode = mode & ~(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.chmod(path, new_mode)
