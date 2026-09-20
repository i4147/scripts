import json
import pathlib
from collections import defaultdict

d = defaultdict()
with pathlib.Path("mm").open(encoding="utf-8") as f:
    for line in f:
        list1 = line.strip().split()
        list2 = ["." + list1[i] for i in range(1, len(list1))]
        d[list1[0]] = list2
with pathlib.Path("mimez.json").open("w", encoding="utf-8") as fj:
    json.dump(d, fj)
