import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def f(x):
    return (x + 1) / (x - 1)


x = np.linspace(-10, 10, 1000)
x = x[x != 1]
fig = plt.subplots(1, 1, figsize=(8, 10))

axes[0].plot(x, f(x), "b-", linewidth=2)

axes[0].axhline(y=0, color="k", linewidth=0.5)
axes[0].axvline(x=0, color="k", linewidth=0.5)
axes[0].axvline(x=1, color="r", linestyle="--", label="مجانب x=1")
axes[0].set_title("f(x) = (x+1)/(x-1)")
axes[0].grid(True)
axes[0].legend()

plt.tight_layout()
plt.savefig("plot1.png", dpi=300, bbox_inches="tight")
