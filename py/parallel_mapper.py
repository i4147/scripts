
from collections.abc import Callable, Iterable
from multiprocessing import get_context
from multiprocessing.pool import Pool
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")
R = TypeVar("R")


def mpf3(
    func: Callable[[T], R],
    items: Iterable[T],
    *,
    workers: int = 4,
    context: str = "spawn",
) -> list[R]:

    if workers < 1:
        raise ValueError(f"workers must be >= 1, got {workers}")

    if not callable(func):
        raise TypeError(f"func must be callable, got {type(func).__name__}")

    items_list = list(items)

    if not items_list:
        return []

    args = [(item,) for item in items_list]

    with get_context(context).Pool(workers) as pool:
        return pool.starmap(func, args)


def parallel_map_chunked(
    func: Callable[[T], R],
    items: Iterable[T],
    *,
    workers: int = 4,
    chunk_size: int | None = None,
    context: str = "spawn",
) -> list[R]:

    items_list = list(items)

    if not items_list:
        return []

    if chunk_size is None:
        chunk_size = max(1, len(items_list) // (workers * 4))

    args = [(item,) for item in items_list]

    with get_context(context).Pool(workers) as pool:
        return pool.starmap(func, args, chunksize=chunk_size)


class ParallelExecutor:
    def __init__(
        self,
        workers: int = 4,
        *,
        context: str = "spawn",
    ) -> None:
        if workers < 1:
            raise ValueError(f"workers must be >= 1, got {workers}")

        self.workers = workers
        self.context = context
        self._pool: Pool | None = None

    def __enter__(self) -> "ParallelExecutor":
        self._pool = get_context(self.context).Pool(self.workers)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._pool:
            self._pool.terminate()
            self._pool.join()
            self._pool = None

    def map(self, func: Callable[[T], R], items: Iterable[T]) -> list[R]:
        if not self._pool:
            raise RuntimeError("Executor must be used as a context manager")

        items_list = list(items)
        if not items_list:
            return []

        args = [(item,) for item in items_list]
        return self._pool.starmap(func, args)



mpf3 = parallel_map  


def process_item(x: int) -> int:
    return x + x



if __name__ == "__main__":
    

    results = parallel_map(process_item, range(10))
    print(f"Basic: {results}")
