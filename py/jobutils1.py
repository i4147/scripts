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
    return mpf(worker_fn, items, num_jobs, *worker_args, **worker_kwargs)


def mpf_joblib(
    process_function: Callable,
    files: list[Path],
    n_jobs: int = -1,
    **kwargs: Any,
) -> list[Any]:
    from joblib import Parallel, delayed

    file_strings = [str(f) for f in files]
    return Parallel(n_jobs=n_jobs)(delayed(process_function)(file_str, **kwargs) for file_str in file_strings)


def mpf_ppe_ac(
    func: Callable,
    files: Iterable[Path],
    workers: int = MAX_WORKERS,
    timeout: int = 30,
) -> list[Any]:
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
