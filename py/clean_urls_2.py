from __future__ import annotations

from urllib.parse import urlparse
import sys

seen = set()
gl = []
fn = sys.argv[1]
with open(fn) as f:
    lines = f.readlines()
    for line in lines:
        try:
            orig = urlparse(line.strip()).netloc
            if orig == "github.com":
                gl.append(line)
            if orig not in seen:
                seen.add(orig)
            else:
                continue
        except:
            print(line)
with open("urls.txt", "w") as fo:
    fo.writelines(f"{k}\n" for k in seen)
with open("gitlinks.txt", "a") as fg:
    fg.write("".join(gl))



