import sys

fn = sys.argv[1]
nl = []
with open(fn) as f:
    for line in f:
        if line.startswith("| "):
            nl.append(line)
with open("ruff_rulles", "w") as f:
    for k in nl:
        f.write(k)
