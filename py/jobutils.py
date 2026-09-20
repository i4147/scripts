from __future__ import annotations

import multiprocessing
import time
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, Executor, Future, ProcessPoolExecutor, ThreadPoolExecutor, wait
from dataclasses import dataclass
from multiprocessing import Pool, get_context
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Any, TypeAlias, TypeVar

T = TypeVar("T")
R = TypeVar("R")

MAX_WORKERS = 8
_MP_CONTEXT = get_context("spawn")


def _get_pool(workers: int = MAX_WORKERS):
    return _MP_CONTEXT.Pool(workers)


def mpf_async(func: Callable, files: Iterable[Path], workers: int = MAX_WORKERS, timeout: int = 30) -> list[Any]:
    files_list = list(files)
    if not files_list:
        return []
    with _get_pool(workers) as pool:
        async_results = [pool.apply_async(func, (file,)) for file in files_list]
        results = []
        for i, async_result in enumerate(async_results):
            try:
                results.append(async_result.get(timeout=timeout))
            except Exception as e:
                print(f"File {i} ({files_list[i]}) failed: {e}")
                results.append(None)
    return results


def mpf_map(func: Callable, files: Iterable[Path], workers: int = MAX_WORKERS) -> list[Any]:
    files_list = list(files)
    if not files_list:
        return []
    with _get_pool(workers) as pool:
        try:
            results = pool.map(func, files_list)
            return list(results)
        except Exception as e:
            print(f"Pool.map failed: {e}")
            return [None] * len(files_list)


def mpf_imap(
    func: Callable, files: Iterable[Path], workers: int = MAX_WORKERS, timeout: int = 30, chunksize: int = 1
) -> list[Any]:
    files_list = list(files)
    if not files_list:
        return []
    results = []
    with _get_pool(workers) as pool:
        for i, result in enumerate(pool.imap_unordered(func, files_list, chunksize=chunksize)):
            try:
                results.append(result)
            except Exception as e:
                print(f"File {i} failed: {e}")
                results.append(None)
    return results


def mpf_imapu(func: Callable, files: Iterable[Path], workers: int = MAX_WORKERS, chunksize: int = 1) -> list[Any]:
    files_list = list(files)
    if not files_list:
        return []
    results = [None] * len(files_list)
    file_to_idx = {str(f): idx for idx, f in enumerate(files_list)}
    with _get_pool(workers) as pool:
        for file_path, result in pool.imap_unordered(lambda f: (f, func(f)), files_list, chunksize=chunksize):
            idx = file_to_idx[str(file_path)]
            results[idx] = result
    return results


def mpf_starmap(
    func: Callable,
    files: Iterable[Path],
    extra_args: list[tuple] | None = None,
    workers: int = MAX_WORKERS,
) -> list[Any]:
    files_list = list(files)
    if not files_list:
        return []
    if extra_args is None:
        extra_args = [() for _ in files_list]
    task_args = [(file, *args) for file, args in zip(files_list, extra_args, strict=False)]
    with _get_pool(workers) as pool:
        try:
            results = pool.starmap(func, task_args)
            return list(results)
        except Exception as e:
            print(f"Pool.starmap failed: {e}")
            return [None] * len(files_list)


def mpf_ppe(func: Callable, files: Iterable[Path], workers: int = MAX_WORKERS, timeout: int = 30) -> list[Any]:
    files_list = list(files)
    if not files_list:
        return []
    results = [None] * len(files_list)
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(func, file): i for i, file in enumerate(files_list)}
        for future in futures:
            idx = futures[future]
            try:
                results[idx] = future.result(timeout=timeout)
            except Exception as e:
                print(f"File {idx} ({files_list[idx]}) failed: {e}")
                results[idx] = None
    return results


def mpf_ppe_ac(func: Callable, files: Iterable[Path], workers: int = MAX_WORKERS, timeout: int = 30) -> list[Any]:
    from concurrent.futures import as_completed

    files_list = list(files)
    if not files_list:
        return []
    results = [None] * len(files_list)
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


def mpf_tpe(func: Callable, files: Iterable[Path], workers: int = MAX_WORKERS, timeout: int = 30) -> list[Any]:
    files_list = list(files)
    if not files_list:
        return []
    results = [None] * len(files_list)
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


@dataclass
class ParallelSummary:
    total: int = 0
    succeeded: int = 0
    failed: int = 0


def _submit_until_full[T, R](
    executor: Executor,
    items: Iterator[T],
    func: Callable[[T], tuple[R, str | None]],
    pending: dict[Future[tuple[R, str | None]], T],
    max_pending: int,
) -> bool:
    exhausted = False
    while len(pending) < max_pending:
        try:
            item = next(items)
        except StopIteration:
            exhausted = True
            break
        pending[executor.submit(func, item)] = item
    return exhausted


def mpf3[T, R](
    func: Callable[[T], tuple[R, str | None]],
    items: Iterable[T],
    *,
    max_workers: int = MAX_WORKERS,
    max_pending_factor: int = 8,
    on_success: Callable[[T, R], None] | None = None,
    on_error: Callable[[T, str], None] | None = None,
    executor_factory: Callable[[int], Executor] | None = None,
) -> ParallelSummary:
    max_workers = MAX_WORKERS
    if executor_factory is None:
        executor_factory = ProcessPoolExecutor
    max_pending = max(max_pending_factor * max_workers, max_workers)
    summary = ParallelSummary()
    item_iterator = iter(items)
    pending: dict[Future[tuple[R, str | None]], T] = {}
    with executor_factory(max_workers) as executor:
        exhausted = _submit_until_full(
            executor,
            item_iterator,
            func,
            pending,
            max_pending,
        )
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                item = pending.pop(future)
                summary.total += 1
                try:
                    result, error = future.result()
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    result = None
                if error is not None:
                    summary.failed += 1
                    if on_error:
                        on_error(item, error)
                else:
                    summary.succeeded += 1
                    if on_success:
                        on_success(item, result)
            if not exhausted:
                exhausted = _submit_until_full(
                    executor,
                    item_iterator,
                    func,
                    pending,
                    max_pending,
                )
    return summary


def mpf(worker_fn: Callable, items: list[Any], num_jobs: int = 1, *worker_args, **worker_kwargs) -> list[Any]:
    if not items:
        return []
    pool = multiprocessing.Pool(num_jobs)
    async_results = []
    try:
        for item in items:
            result = pool.apply_async(worker_fn, args=(item, *worker_args), kwds=worker_kwargs)
            async_results.append(result)
        results = []
        for async_result in async_results:
            try:
                results.append(async_result.get())
            except Exception as e:
                raise type(e)(f"Worker failed: {e}") from e
        return results
    finally:
        pool.close()
        pool.join()


def mpf2(worker_fn: Callable, items: list[Any], num_jobs: int = 1, *worker_args, **worker_kwargs) -> list[Any]:
    if not items:
        return []
    pool = multiprocessing.Pool(num_jobs)
    async_results = deque()
    try:
        for item in items:
            result = pool.apply_async(worker_fn, args=(item, *worker_args), kwds=worker_kwargs)
            async_results.append(result)
        results = deque()
        while async_results:
            async_result = async_results.popleft()
            try:
                results.append(async_result.get())
            except Exception as e:
                raise type(e)(f"Worker failed: {e}") from e
        return list(results)
    finally:
        pool.close()
        pool.join()


def mpf_joblib(process_function: Callable, files: list[Path], **kwargs):
    from joblib import Parallel, delayed

    file_strings = [str(f) for f in files]
    return Parallel(n_jobs=-1)(delayed(process_function)(file_str, **kwargs) for file_str in file_strings)
