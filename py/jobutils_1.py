i had these functions as part of my custom python module named dh

# filename: jobutils.py

from __future__ import annotations

import os
import time
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import (
    FIRST_COMPLETED,
    Executor,
    Future,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    TimeoutError as FutureTimeoutError,
    wait,
)
from functools import partial
from multiprocessing import Pool, get_context
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Any, ParamSpec, TypeVar

T = TypeVar("T")
R = TypeVar("R")
P = ParamSpec("P")
MAX_WORKERS = 8
DEFAULT_TIMEOUT = 30
get_context("spawn")
ExecutorFactory = Callable[..., Executor]


def _call_with_index[R](func: Callable[[Path], R], indexed_file: tuple[int, Path]) -> tuple[int, R]:
    """Invoke ``func`` with a :class:`Path` while preserving its index."""
    idx, file = indexed_file
    return idx, func(file)


def mpf_async[**P, R](
    func: Callable[P, R],
    files: Iterable[Path],
    workers: int = MAX_WORKERS,
    timeout: int = DEFAULT_TIMEOUT,
    *args: P.args,
    **kwargs: P.kwargs,
) -> list[R | None]:
    """Run ``func`` over ``files`` using ``Pool.apply_async``.
    Each file is submitted independently, and results are collected in the
    original order. Failures are logged and recorded as ``None``.
    Args:
        func: Callable to apply to each file.
        files: Iterable of :class:`Path` objects.
        workers: Number of worker processes.
        timeout: Per-task timeout in seconds.
        *args: Extra positional arguments forwarded to ``func``.
        **kwargs: Extra keyword arguments forwarded to ``func``.
    Returns:
        List of results (or ``None`` for failures) in input order.
    """
    files_list = list(files)
    if not files_list:
        return []
    with Pool(workers) as pool:
        async_results = [pool.apply_async(func, (file, *args), kwargs) for file in files_list]
        results: list[R | None] = []
        for i, async_result in enumerate(async_results):
            try:
                results.append(async_result.get(timeout=timeout))
            except Exception as e:
                print(f"File {i} ({files_list[i]}) failed: {e}")
                results.append(None)
    return results


def mpf_map[R](
    func: Callable[[Path], R],
    files: Iterable[Path],
    workers: int = MAX_WORKERS,
    chunksize: int = 1,
) -> list[R | None]:
    """Apply ``func`` to ``files`` with ``Pool.map``.
    Args:
        func: Callable accepting a :class:`Path`.
        files: Iterable of :class:`Path` objects.
        workers: Number of worker processes.
        chunksize: Number of items per task chunk.
    Returns:
        List of results in input order; ``None`` entries on failure.
    """
    files_list = list(files)
    if not files_list:
        return []
    with Pool(workers) as pool:
        try:
            return list(pool.map(func, files_list, chunksize=chunksize))
        except Exception as e:
            print(f"Pool.map failed: {e}")
            return [None] * len(files_list)


def mpf_imap[R](
    func: Callable[[Path], R],
    files: Iterable[Path],
    workers: int = MAX_WORKERS,
    chunksize: int = 1,
    ordered: bool = True,
) -> list[R | None]:
    """Apply ``func`` to ``files`` with ``Pool.imap`` / ``imap_unordered``.
    Args:
        func: Callable accepting a :class:`Path`.
        files: Iterable of :class:`Path` objects.
        workers: Number of worker processes.
        chunksize: Number of items per task chunk.
        ordered: If ``True`` use ``imap``; otherwise ``imap_unordered``.
    Returns:
        List of results.
    """
    files_list = list(files)
    if not files_list:
        return []
    results: list[R | None] = []
    with Pool(workers) as pool:
        imap_func = pool.imap if ordered else pool.imap_unordered
        for result in imap_func(func, files_list, chunksize=chunksize):
            results.append(result)
    return results


def mpf_imapu[R](
    func: Callable[[Path], R],
    files: Iterable[Path],
    workers: int = MAX_WORKERS,
    chunksize: int = 1,
) -> list[R | None]:
    """..."""
    files_list = list(files)
    if not files_list:
        return []
    results: list[R | None] = [None] * len(files_list)
    bound = partial(_call_with_index, func)
    indexed = list(enumerate(files_list))
    with Pool(workers) as pool:
        for idx, result in pool.imap_unordered(bound, indexed, chunksize=chunksize):
            results[idx] = result
    return results


def mpf_starmap[**P, R](
    func: Callable[P, R],
    files: Iterable[Path],
    extra_args: Sequence[tuple] | None = None,
    workers: int = MAX_WORKERS,
) -> list[R | None]:
    """Apply ``func`` to ``files`` with ``Pool.starmap``.
    ``extra_args`` allows passing additional positional arguments per file.
    Each entry in ``extra_args`` is splatted after the file argument.
    Args:
        func: Callable whose first parameter is a :class:`Path`.
        files: Iterable of :class:`Path` objects.
        extra_args: Optional per-file extra positional argument tuples.
        workers: Number of worker processes.
    Returns:
        List of results; ``None`` entries on failure.
    Raises:
        ValueError: If ``extra_args`` length differs from ``files`` length.
    """
    files_list = list(files)
    if not files_list:
        return []
    if extra_args is None:
        extra_args = [() for _ in files_list]
    elif len(extra_args) != len(files_list):
        raise ValueError("extra_args length must match files length")
    task_args = [(file, *args) for file, args in zip(files_list, extra_args)]
    with Pool(workers) as pool:
        try:
            return list(pool.starmap(func, task_args))
        except Exception as e:
            print(f"Pool.starmap failed: {e}")
            return [None] * len(files_list)


def mpf_ppe[R](
    func: Callable[[Path], R],
    files: Iterable[Path],
    workers: int = MAX_WORKERS,
    timeout: int = DEFAULT_TIMEOUT,
    use_as_completed: bool = False,
) -> list[R | None]:
    """Process ``files`` with :class:`ProcessPoolExecutor`.
    Args:
        func: Callable accepting a :class:`Path`.
        files: Iterable of :class:`Path` objects.
        workers: Maximum number of worker processes.
        timeout: Timeout forwarded to ``Future.result`` / ``as_completed``.
        use_as_completed: If ``True`` consume futures via ``as_completed``;
            otherwise iterate the futures dict directly.
    Returns:
        List of results in input order; ``None`` entries on failure.
    """
    files_list = list(files)
    if not files_list:
        return []
    results: list[R | None] = [None] * len(files_list)
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(func, file): i for i, file in enumerate(files_list)}
        if use_as_completed:
            from concurrent.futures import as_completed

            iterator: Iterable[Future[R]] = as_completed(futures, timeout=timeout)
        else:
            iterator = iter(futures)
        for future in iterator:
            idx = futures[future]
            try:
                results[idx] = future.result(timeout=timeout)
            except Exception as e:
                print(f"File {idx} ({files_list[idx]}) failed: {e}")
                results[idx] = None
    return results


def mpf_tpe[R](
    func: Callable[[Path], R],
    files: Iterable[Path],
    workers: int = MAX_WORKERS,
    timeout: int = DEFAULT_TIMEOUT,
) -> list[R | None]:
    """Process ``files`` with :class:`ThreadPoolExecutor`.
    Args:
        func: Callable accepting a :class:`Path`.
        files: Iterable of :class:`Path` objects.
        workers: Maximum number of worker threads.
        timeout: Timeout forwarded to ``Future.result``.
    Returns:
        List of results in input order; ``None`` entries on failure.
    """
    files_list = list(files)
    if not files_list:
        return []
    results: list[R | None] = [None] * len(files_list)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(func, file): i for i, file in enumerate(files_list)}
        for future in futures:
            idx = futures[future]
            try:
                results[idx] = future.result(timeout=timeout)
            except Exception as e:
                print(f"File {idx} ({files_list[idx]}) failed: {e}")
                results[idx] = None
    return results


def mpf(
    worker_fn: Callable,
    items: list[Any],
    num_jobs: int = 1,
    *worker_args: Any,
    **worker_kwargs: Any,
) -> list[Any]:
    """Run ``worker_fn`` over ``items`` using ``Pool.apply_async``.
    Args:
        worker_fn: Callable applied to each item.
        items: Items to process.
        num_jobs: Number of worker processes.
        *worker_args: Extra positional arguments for ``worker_fn``.
        **worker_kwargs: Extra keyword arguments for ``worker_fn``.
    Returns:
        List of results in input order.
    """
    if not items:
        return []
    with Pool(num_jobs) as pool:
        async_results = [pool.apply_async(worker_fn, args=(item, *worker_args), kwds=worker_kwargs) for item in items]
        return [result.get() for result in async_results]


def mpf2(
    worker_fn: Callable,
    items: list[Any],
    num_jobs: int = 1,
    *worker_args: Any,
    **worker_kwargs: Any,
) -> list[Any]:
    """Alias for :func:`mpf` retained for backwards compatibility."""
    return mpf(worker_fn, items, num_jobs, *worker_args, **worker_kwargs)


def mpf_joblib(
    process_function: Callable,
    files: list[Path],
    n_jobs: int = -1,
    **kwargs: Any,
) -> list[Any]:
    """Run ``process_function`` over ``files`` using ``joblib.Parallel``.
    Args:
        process_function: Callable accepting a string path.
        files: List of :class:`Path` objects.
        n_jobs: ``joblib`` worker count (``-1`` uses all CPUs).
        **kwargs: Extra keyword arguments forwarded to ``process_function``.
    Returns:
        List of results in input order.
    """
    from joblib import Parallel, delayed

    file_strings = [str(f) for f in files]
    return Parallel(n_jobs=n_jobs)(delayed(process_function)(file_str, **kwargs) for file_str in file_strings)


def mpf_ppe_ac(
    func: Callable,
    files: Iterable[Path],
    workers: int = MAX_WORKERS,
    timeout: int = 30,
) -> list[Any]:
    """Run ``func`` over ``files`` with ``ProcessPoolExecutor`` + ``as_completed``.
    Args:
        func: Callable accepting a :class:`Path`.
        files: Iterable of :class:`Path` objects.
        workers: Maximum number of worker processes.
        timeout: Timeout forwarded to ``as_completed``.
    Returns:
        List of results in input order; ``None`` entries on failure.
    """
    from concurrent.futures import as_completed

    files_list = list(files)
    if not files_list:
        return []
    results: list[Any] = [None] * len(files_list)
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(func, file): i for i, file in enumerate(files_list)}
        for future in as_completed(futures, timeout=timeout):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                print(f"File {idx} ({files_list[idx]}) failed: {e}")
                results[idx] = None
    return results


def mpf3[T, R](
    func: Callable[[T], tuple[R, str | None]],
    items: Iterable[T],
    *,
    max_workers: int = MAX_WORKERS,
    max_pending_factor: int = 8,
    timeout: float | None = DEFAULT_TIMEOUT,
    on_error: Callable[[T, str], None] | None = None,
    on_timeout: Callable[[T], None] | None = None,
    executor_type: ExecutorFactory = ProcessPoolExecutor,
    executor_kwargs: dict[str, Any] | None = None,
) -> list[R | None]:
    items_list = list(items)
    if not items_list:
        return []
    if executor_kwargs is None:
        executor_kwargs = {}
    max_pending = max(max_pending_factor * max_workers, max_workers)
    results: list[R | None] = [None] * len(items_list)
    item_iterator = iter(enumerate(items_list))
    pending: dict[Future[tuple[R, str | None]], tuple[int, T, float]] = {}
    with executor_type(max_workers=max_workers, **executor_kwargs) as executor:
        exhausted = False
        while len(pending) < max_pending and not exhausted:
            try:
                idx, item = next(item_iterator)
                future = executor.submit(func, item)
                pending[future] = (idx, item, time.time())
            except StopIteration:
                exhausted = True
        while pending:
            done, _ = wait(pending.keys(), return_when=FIRST_COMPLETED)
            for future in done:
                idx, item, start_time = pending.pop(future)
                try:
                    if timeout is not None:
                        elapsed = time.time() - start_time
                        remaining_timeout = max(0.0, timeout - elapsed)
                        if remaining_timeout == 0:
                            raise FutureTimeoutError(f"Task timed out after {timeout}s")
                        result, error = future.result(timeout=remaining_timeout)
                    else:
                        result, error = future.result()
                    if error is not None:
                        if on_error:
                            on_error(item, error)
                    else:
                        results[idx] = result
                except FutureTimeoutError:
                    future.cancel()
                    if on_timeout:
                        on_timeout(item)
                    elif on_error:
                        on_error(item, f"Timeout after {timeout}s")
                except Exception as exc:
                    error_msg = f"{type(exc).__name__}: {exc}"
                    if on_error:
                        on_error(item, error_msg)
            if not exhausted:
                while len(pending) < max_pending:
                    try:
                        idx, item = next(item_iterator)
                        future = executor.submit(func, item)
                        pending[future] = (idx, item, time.time())
                    except StopIteration:
                        exhausted = True
                        break
    return results


def mpf_as[T, R](func: Callable[[T], R], files: Iterable[T]) -> list[R]:
    results: list[R] = []
    with Pool(8) as pool:
        pending: deque = deque()
        for f in files:
            pending.append(pool.apply_async(func, (f,)))
            if len(pending) > 32:
                results.append(pending.popleft().get())
        while pending:
            results.append(pending.popleft().get())
    return results


def mpf_bounded[T, R](
    func: Callable[[T], R],
    files: Iterable[T],
    *,
    processes: int | None = None,
    max_inflight: int | None = None,
) -> list[R]:
    processes = processes or os.cpu_count() or 1
    max_inflight = max_inflight or 2 * processes
    results: list[R] = []
    with Pool(processes) as pool:
        pending: deque[AsyncResult[R]] = deque()
        for f in files:
            if len(pending) >= max_inflight:
                results.append(pending.popleft().get())
            pending.append(pool.apply_async(func, (f,)))
        while pending:
            results.append(pending.popleft().get())
    return results


def mpf_stream[T, R](
    func: Callable[[T], R],
    files: Iterable[T],
    *,
    processes: int | None = None,
    chunksize: int = 1,
) -> Iterator[R]:
    processes = processes or os.cpu_count() or 1
    with Pool(processes) as pool:
        yield from pool.imap(func, files, chunksize=chunksize)


def mpf_imap2[T, R](
    func: Callable[[T], R],
    files: Iterable[T],
    *,
    processes: int | None = None,
    chunksize: int = 1,
) -> list[R]:
    processes = processes or os.cpu_count() or 1
    with Pool(processes) as pool:
        return list(pool.imap(func, files, chunksize=chunksize))


im going to replace it with
# filename: jobutils.py

"""Core implementation of :mod:`jobutils`."""

from __future__ import annotations

import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from enum import Enum
from functools import partial
from typing import Any, Callable, Iterable, Sequence, Type

__all__ = ["MAX_WORKERS", "DEFAULT_CHUNKSIZE", "PoolMethod", "run_parallel"]

#: Default number of workers used by :func:`run_parallel`.
MAX_WORKERS: int = 8

#: Default chunk size for the multiprocessing.Pool methods.
#: ``None`` lets the pool auto-compute it (one chunk per ~``4 * workers``
#: items), which matches the stdlib default since Python 3.5.
DEFAULT_CHUNKSIZE: int | None = None

#: Default chunk size for ProcessPoolExecutor (stdlib default is 1).
DEFAULT_EXECUTOR_CHUNKSIZE: int = 1


class PoolMethod(str, Enum):
    """All supported execution backends."""

    # --- multiprocessing.Pool ------------------------------------------------
    MAP = "map"
    MAP_ASYNC = "map_async"
    STARMAP = "starmap"
    STARMAP_ASYNC = "starmap_async"
    IMAP = "imap"
    IMAP_UNORDERED = "imap_unordered"
    APPLY = "apply"
    APPLY_ASYNC = "apply_async"

    # --- third-party / stdlib executors -------------------------------------
    JOBLIB = "joblib"
    PROCESS_POOL = "process_pool"   # concurrent.futures.ProcessPoolExecutor
    THREAD_POOL = "thread_pool"     # concurrent.futures.ThreadPoolExecutor

    @classmethod
    def parse(cls, value: "str | PoolMethod") -> "PoolMethod":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).lower())
        except ValueError as exc:
            valid = ", ".join(m.value for m in cls)
            raise ValueError(
                f"unknown method {value!r}; expected one of: {valid}"
            ) from exc

    @property
    def is_mp_pool(self) -> bool:
        return self.value in _MP_POOL_METHODS


_MP_POOL_METHODS = frozenset({
    "map", "map_async", "starmap", "starmap_async",
    "imap", "imap_unordered", "apply", "apply_async",
})


# ---------------------------------------------------------------------------
# multiprocessing.Pool dispatch
# ---------------------------------------------------------------------------

def _dispatch_mp_pool(
    pool: mp.pool.Pool,
    method: PoolMethod,
    func: Callable[..., Any],
    items: list[Any],
    chunksize: int | None,
) -> list[Any]:
    if method is PoolMethod.MAP:
        return pool.map(func, items, chunksize=chunksize)
    if method is PoolMethod.MAP_ASYNC:
        return pool.map_async(func, items, chunksize=chunksize).get()
    if method in (PoolMethod.STARMAP, PoolMethod.STARMAP_ASYNC):
        args = [item if isinstance(item, tuple) else (item,) for item in items]
        if method is PoolMethod.STARMAP:
            return pool.starmap(func, args, chunksize=chunksize)
        return pool.starmap_async(func, args, chunksize=chunksize).get()
    if method is PoolMethod.IMAP:
        return list(pool.imap(func, items, chunksize=chunksize))
    if method is PoolMethod.IMAP_UNORDERED:
        return list(pool.imap_unordered(func, items, chunksize=chunksize))
    if method is PoolMethod.APPLY:
        return [pool.apply(func, args=(item,)) for item in items]
    if method is PoolMethod.APPLY_ASYNC:
        futs = [pool.apply_async(func, args=(item,)) for item in items]
        return [f.get() for f in futs]
    raise AssertionError(f"unhandled mp.pool method: {method}")


def _run_mp_pool(
    method, func, items, workers, chunksize,
    initializer, initargs, maxtasksperchild, context,
) -> list[Any]:
    ctx = mp.get_context(context) if context else mp.get_context()
    with ctx.Pool(
        processes=workers,
        initializer=initializer,
        initargs=tuple(initargs),
        maxtasksperchild=maxtasksperchild,
    ) as pool:
        return _dispatch_mp_pool(pool, method, func, items, chunksize)


# ---------------------------------------------------------------------------
# concurrent.futures dispatch (process + thread)
# ---------------------------------------------------------------------------

def _run_executor(
    executor_cls: Type[ProcessPoolExecutor] | Type[ThreadPoolExecutor],
    func: Callable[..., Any],
    items: list[Any],
    workers: int,
    chunksize: int | None,
    unpack: bool,
    initializer: Callable[..., Any] | None,
    initargs: Sequence[Any],
    maxtasksperchild: int | None,
) -> list[Any]:
    kwargs: dict[str, Any] = {"max_workers": workers}
    if initializer is not None:
        kwargs["initializer"] = initializer
        kwargs["initargs"] = tuple(initargs)
    # ``max_tasks_per_child`` (3.11+) exists only on ProcessPoolExecutor.
    if maxtasksperchild is not None and executor_cls is ProcessPoolExecutor:
        kwargs["max_tasks_per_child"] = maxtasksperchild

    with executor_cls(**kwargs) as ex:
        # Order-preserving path — submission order == result order.
        if unpack:
            futs = [
                ex.submit(func, *(item if isinstance(item, tuple) else (item,)))
                for item in items
            ]
            return [f.result() for f in futs]

        if executor_cls is ProcessPoolExecutor:
            return list(ex.map(func, items, chunksize=chunksize or DEFAULT_EXECUTOR_CHUNKSIZE))
        # ThreadPoolExecutor.map has no chunksize argument.
        return list(ex.map(func, items))


# ---------------------------------------------------------------------------
# joblib dispatch
# ---------------------------------------------------------------------------

def _run_joblib(
    func: Callable[..., Any],
    items: list[Any],
    workers: int,
    unpack: bool,
) -> list[Any]:
    try:
        from joblib import Parallel, delayed
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "the 'joblib' backend requires joblib — `pip install joblib`"
        ) from exc

    # joblib uses ``n_jobs``; ``None`` means "1 job", ``-1`` means "all CPUs".
    n_jobs = -1 if workers is None else workers

    if unpack:
        return Parallel(n_jobs=n_jobs)(
            delayed(func)(*(item if isinstance(item, tuple) else (item,)))
            for item in items
        )
    return Parallel(n_jobs=n_jobs)(delayed(func)(item) for item in items)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_parallel(
    func: Callable[..., Any],
    items: Iterable[Any],
    method: "str | PoolMethod" = PoolMethod.IMAP_UNORDERED,
    *,
    workers: int = MAX_WORKERS,
    chunksize: int | None = DEFAULT_CHUNKSIZE,
    unpack: bool = False,
    func_args: Sequence[Any] = (),
    func_kwargs: dict[str, Any] | None = None,
    initializer: Callable[..., Any] | None = None,
    initargs: Sequence[Any] = (),
    maxtasksperchild: int | None = None,
    context: str | None = None,
) -> list[Any]:
    """Run ``func`` over ``items`` using the requested backend.

    Parameters
    ----------
    func, items
        The workhorse and its inputs (``pathlib.Path`` inputs are fine).
    method
        Which execution backend to use. One of:

        * ``multiprocessing.Pool``: ``map``, ``map_async``, ``starmap``,
          ``starmap_async``, ``imap``, ``imap_unordered`` (default),
          ``apply``, ``apply_async``.
        * ``joblib``: ``"joblib"`` (requires ``pip install joblib``).
        * ``concurrent.futures``: ``"process_pool"`` (ProcessPoolExecutor)
          or ``"thread_pool"`` (ThreadPoolExecutor — good for I/O bound work
          or C extensions that release the GIL).
    workers
        Number of workers. Defaults to :data:`MAX_WORKERS` (8). ``None``
        delegates to the backend default (``cpu_count`` for Pool/executors,
        single job for joblib).
    chunksize
        Batch size hint. Honoured by ``multiprocessing.Pool`` methods and
        ``ProcessPoolExecutor``; ignored by ``ThreadPoolExecutor`` and joblib.
        Defaults to :data:`DEFAULT_CHUNKSIZE` (``None`` = auto) for Pool
        methods, ``1`` for ``ProcessPoolExecutor``.
    unpack
        If ``True``, each item is unpacked as positional arguments to ``func``
        (starmap-style) — for the new backends only. The ``multiprocessing``
        starmap variants already imply this; leave ``unpack`` at its default
        for them.
    func_args, func_kwargs
        Extra args bound to ``func`` via :func:`functools.partial` before
        dispatch. Works for every backend.
    initializer, initargs
        Per-worker setup. Supported by ``multiprocessing.Pool`` and both
        ``concurrent.futures`` executors (not by joblib).
    maxtasksperchild
        Recycle workers after N tasks. Supported by ``multiprocessing.Pool``
        and ``ProcessPoolExecutor`` (as ``max_tasks_per_child``, 3.11+).
    context
        ``"fork"``, ``"spawn"``, ``"forkserver"`` — ``multiprocessing`` only.

    Returns
    -------
    list
        Results in backend-specific order: ordered for ``map``, ``starmap``,
        ``imap``, ``apply*``, all executor methods, and joblib;
        ``imap_unordered`` is the only unordered one.
    """
    if not callable(func):
        raise TypeError("`func` must be callable")

    pool_method = PoolMethod.parse(method)

    if func_args or func_kwargs:
        func = partial(func, *func_args, **(func_kwargs or {}))

    items = list(items)

    if pool_method.is_mp_pool:
        return _run_mp_pool(
            pool_method, func, items, workers, chunksize,
            initializer, initargs, maxtasksperchild, context,
        )

    if pool_method is PoolMethod.JOBLIB:
        if initializer is not None or maxtasksperchild is not None:
            raise ValueError(
                "the 'joblib' backend does not support initializer/"
                "maxtasksperchild; use 'process_pool' or 'map' instead"
            )
        return _run_joblib(func, items, workers, unpack)

    if pool_method is PoolMethod.PROCESS_POOL:
        return _run_executor(
            ProcessPoolExecutor, func, items, workers, chunksize,
            unpack, initializer, initargs, maxtasksperchild,
        )

    if pool_method is PoolMethod.THREAD_POOL:
        if maxtasksperchild is not None:
            raise ValueError(
                "ThreadPoolExecutor does not support maxtasksperchild"
            )
        return _run_executor(
            ThreadPoolExecutor, func, items, workers, chunksize,
            unpack, initializer, initargs, None,
        )

    raise AssertionError(f"unhandled method: {pool_method}")


make required changes to my new jobutils.py 
so that i can keep backward compatibility

