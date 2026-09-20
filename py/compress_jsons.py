import brotli
import os
import glob
from pathlib import Path

json_dir = Path("googleapiclient/discovery_cache/documents/")
json_files = glob.glob(str(json_dir / "*.json"))

for json_path in json_files:
    with open(json_path, "rb") as f:
        data = f.read()

    compressed = brotli.compress(data, quality=11)

    br_path = json_path + ".br"
    with open(br_path, "wb") as f:
        f.write(compressed)
