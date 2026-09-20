import base64
from pathlib import Path

fn = Path("2")
lines = fn.read_text().splitlines()

for line in lines:
    line = line.strip()
    try:
        deco = base64.base64decode(line)
        print(deco)
    except:
        pass
for line in lines:
    line = line.strip()[2:]
    try:
        deco = base64.base64decode(line.strip())
        print(deco)
    except:
        pass
