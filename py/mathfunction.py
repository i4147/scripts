import matplotlib.pyplot as plt
import numpy as np


def f(x):
    return (x**2 - 2 * x + 6) / (x - 1)


x = np.linspace(-10, 10, 1000)
y = f(x)
plt.figure(figsize=(8, 6))
plt.plot(
    x,
    y,
    label=r"$f(x) = \frac{x^2 - 2x + 6}{x - 1}$",
)
plt.axvline(
    x=1,
    color="red",
    linestyle="--",
    label="Vertical asymptote at x=1",
)
plt.axhline(y=0, color="black", linewidth=0.5)
plt.xlabel("x")
plt.ylabel("f(x)")
plt.title("Plot of f(x) = (x^2 - 2x + 6)/(x - 1)")
plt.legend()
plt.grid(True)
plt.show()
