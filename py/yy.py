import sys

from dh import is_digit

fn = sys.argv[1]

nl = []
rest = []
with open(fn) as f:
    for line in f:
        striped = line.strip()
        if not is_digit(striped, ps=True):
            rest.append(line)
with open(fn, "w") as f:
    for k in rest:
        f.write(k)
