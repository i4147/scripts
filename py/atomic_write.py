from __future__ import annotations
import contextlib
import fcntl
import io
import tempfile
from pathlib import Path

DEFAULT_MODE = "w"


def _proper_fsync(fd: int) -> None:
    return None


if hasattr(fcntl, "F_FULLFSYNC"):

    def _proper_fsync(fd: int) -> None:
        fcntl.fcntl(fd, fcntl.F_FULLFSYNC)

else:

    def _proper_fsync(fd: int) -> None:
        import os

        os.fsync(fd)


def _sync_directory(directory: Path) -> None:
    import os

    fd = os.open(directory, 0)
    try:
        _proper_fsync(fd)
    finally:
        os.close(fd)


def _replace_atomic(src: Path, dst: Path) -> None:
    import os

    os.rename(src, dst)
    _sync_directory(dst.parent)


def _move_atomic(src: Path, dst: Path) -> None:
    import os

    os.link(src, dst)
    os.unlink(src)
    _sync_directory(dst.parent)
    if src.parent != dst.parent:
        _sync_directory(src.parent)


class AtomicWriter:
    def __init__(
        self,
        path: str | Path,
        mode: str = DEFAULT_MODE,
        overwrite: bool = False,
        **open_kwargs,
    ) -> None:
        if "a" in mode:
            raise ValueError("Appending to an existing file is not supported.")
        if "x" in mode:
            raise ValueError("Use the `overwrite`-parameter instead.")
        if "w" not in mode:
            raise ValueError("AtomicWriters can only be written to.")
        self._path = Path(path)
        self._mode = mode
        self._overwrite = overwrite
        self._open_kwargs = open_kwargs

    def open(self):
        return self._open(self._get_fileobject)

    @contextlib.contextmanager
    def _open(self, get_fileobject):
        f = None
        success = False
        try:
            with get_fileobject() as f:
                yield f
                self.sync(f)
                self.commit(f)
                success = True
        finally:
            if not success and f is not None:
                try:
                    self.rollback(f)
                except Exception:
                    pass

    def _get_fileobject(
        self,
        suffix: str = "",
        prefix: str = tempfile.gettempprefix(),
        dir: Path | None = None,
        **kwargs,
    ):
        target_dir = dir if dir is not None else self._path.parent
        fd, name = tempfile.mkstemp(
            suffix=suffix,
            prefix=prefix,
            dir=str(target_dir),
        )
        import os

        os.close(fd)
        kwargs["mode"] = self._mode
        kwargs["file"] = name
        return io.open(**kwargs)

    def sync(self, f) -> None:
        f.flush()
        _proper_fsync(f.fileno())

    def commit(self, f) -> None:
        src = Path(f.name)
        dst = self._path
        if self._overwrite:
            _replace_atomic(src, dst)
        else:
            _move_atomic(src, dst)

    def rollback(self, f) -> None:
        Path(f.name).unlink()


def atomic_write(path: str | Path, writer_cls: type[AtomicWriter] = AtomicWriter, **cls_kwargs):
    return writer_cls(path, **cls_kwargs).open()
