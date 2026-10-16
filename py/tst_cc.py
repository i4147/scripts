from radon.complexity import cc_rank
from radon.metrics import mi_rank

for i in range(100):
    print(f"cc_rank {i} = {cc_rank(i)}")
    print(f"mi_rank {i} = {mi_rank(i)}")
