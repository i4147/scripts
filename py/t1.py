from dh import cprint
from secrets import randbelow

"""
try:
    while True:
        a,b,c=randbelow(256),randbelow(256),randbelow(256)
        cprint("A",(a,b,c),end="")
except KeyboardInterrupt:
    import sys
    sys.exit(1)

"""

counter = 0
for i in range(0, 256, 5):
    for j in range(0, 256, 5):
        for k in range(0, 256, 5):
            counter += 1
            cprint(f"{counter}", (i, j, k), end=" ")
