import bz2
import gzip
import importlib
import io
import lzma
import os
import shutil
import tarfile
import tempfile
import zipfile
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO, Iterator, Optional, Union


class ArchiveInPlaceError(Exception):
    pass


class UnsupportedFormatError(ArchiveInPlaceError):
    pass



ProcessorFunc = Callable[[bytes, str], bytes]
FilterFunc = Callable[[str], bool]


class ArchiveProcessor:
    COMPRESSION_EXTENSIONS: dict[str, str] = {
        ".gz": "gzip",
        ".bz2": "bzip2",
        ".xz": "lzma",
        ".zst": "zstandard",
        ".br": "brotli",
        ".bz3": "bzip3",
        ".snappy": "snappy",
        ".lz4": "lz4",
    }
    ARCHIVE_EXTENSIONS: dict[str, str] = {
        ".zip": "zip",
        ".whl": "zip",
        ".tar": "tar",
        ".7z": "7zip",
    }
    TAR_COMPRESSION: dict[str, str] = {
        ".tar.gz": "gz",
        ".tgz": "gz",
        ".tar.xz": "xz",
        ".txz": "xz",
        ".tar.zst": "zst",
        ".tar.7z": "7z",
        ".tar.br": "br",
        ".tar.bz2": "bz2",
        ".tbz2": "bz2",
        ".tar.bz3": "bz3",
        ".tar.snappy": "snappy",
        ".tar.lz4": "lz4",
    }

    def __init__(self, archive_path: Union[str, os.PathLike[str]]) -> None:
        self.archive_path: Path = Path(archive_path)
        if not self.archive_path.exists():
            raise FileNotFoundError(f"Archive not found: {archive_path}")
        self.format_type: str = ""
        self.compression: Optional[str] = None
        self._detect_format()

    def _detect_format(self) -> None:
        filename = self.archive_path.name.lower()
        for ext, compression in self.TAR_COMPRESSION.items():
            if filename.endswith(ext):
                self.format_type = "tar"
                self.compression = compression
                return
        for ext, archive_type in self.ARCHIVE_EXTENSIONS.items():
            if filename.endswith(ext):
                self.format_type = archive_type
                self.compression = None
                return
        for ext, compression in self.COMPRESSION_EXTENSIONS.items():
            if filename.endswith(ext):
                self.format_type = "single"
                self.compression = compression
                return
        raise UnsupportedFormatError(f"Unsupported archive format: {filename}")

    def _tar_read_mode(self) -> str:
        if self.compression is None:
            return "r"
        if self.compression == "gz":
            return "r:gz"
        if self.compression == "bz2":
            return "r:bz2"
        if self.compression == "xz":
            return "r:xz"
        
        return "r:*"

    def _tar_write_mode(self) -> str:
        if self.compression is None:
            return "w"
        if self.compression == "gz":
            return "w:gz"
        if self.compression == "bz2":
            return "w:bz2"
        if self.compression == "xz":
            return "w:xz"
        return "w"

    @contextmanager
    def _open_tar_read(self) -> Iterator[tarfile.TarFile]:
        with tarfile.open(self.archive_path, self._tar_read_mode()) as archive:
            yield archive

    @contextmanager
    def _open_zip_read(self) -> Iterator[zipfile.ZipFile]:
        with zipfile.ZipFile(self.archive_path, "r") as archive:
            yield archive

    @contextmanager
    def _open_7z_read(self) -> Iterator[Any]:
        import py7zr

        with py7zr.SevenZipFile(self.archive_path, "r") as archive:
            yield archive

    def _get_compression_handler(self, compression: str) -> Optional[Any]:
        handlers: dict[str, Any] = {
            "gzip": gzip,
            "bzip2": bz2,
            "lzma": lzma,
        }
        lazy_imports = {
            "zstandard": "zstandard",
            "brotli": "brotli",
            "bzip3": "bz3",
            "snappy": "cramjam",
            "lz4": "lz4.frame",
        }
        if compression in handlers:
            return handlers[compression]
        if compression in lazy_imports:
            return importlib.import_module(lazy_imports[compression])
        return None

    def _decompress_data(self, data: bytes, compression: Optional[str]) -> bytes:
        if compression is None:
            return data
        handler = self._get_compression_handler(compression)
        if handler is None:
            raise UnsupportedFormatError(f"Unsupported compression: {compression}")
        try:
            if compression == "gzip":
                return gzip.decompress(data)
            if compression == "bzip2":
                return bz2.decompress(data)
            if compression == "lzma":
                return lzma.decompress(data)
            if compression == "zstandard":
                return handler.ZstdDecompressor().decompress(data)
            if compression == "brotli":
                return handler.decompress(data)
            if compression == "bzip3":
                return handler.decompress(data)
            if compression == "snappy":
                return handler.decompress(data)
            if compression == "lz4":
                return handler.decompress(data)
        except Exception as e:
            raise ArchiveInPlaceError(f"Failed to decompress {compression} data: {e}") from e
        raise UnsupportedFormatError(f"Unsupported compression: {compression}")

    def _compress_data(self, data: bytes, compression: Optional[str]) -> bytes:
        if compression is None:
            return data
        handler = self._get_compression_handler(compression)
        if handler is None:
            raise UnsupportedFormatError(f"Unsupported compression: {compression}")
        try:
            if compression == "gzip":
                return gzip.compress(data)
            if compression == "bzip2":
                return bz2.compress(data)
            if compression == "lzma":
                return lzma.compress(data)
            if compression == "zstandard":
                return handler.ZstdCompressor().compress(data)
            if compression == "brotli":
                return handler.compress(data)
            if compression == "bzip3":
                return handler.compress(data)
            if compression == "snappy":
                return handler.compress(data)
            if compression == "lz4":
                return handler.compress(data)
        except Exception as e:
            raise ArchiveInPlaceError(f"Failed to compress {compression} data: {e}") from e
        raise UnsupportedFormatError(f"Unsupported compression: {compression}")

    def list_files(self) -> list[str]:
        if self.format_type == "single":
            return [self.archive_path.stem]
        if self.format_type == "zip":
            with self._open_zip_read() as archive:
                return archive.namelist()
        if self.format_type == "tar":
            with self._open_tar_read() as archive:
                return [member.name for member in archive.getmembers() if member.isfile()]
        if self.format_type == "7zip":
            with self._open_7z_read() as archive:
                return list(archive.getnames())
        raise UnsupportedFormatError(f"Unsupported archive type: {self.format_type}")

    def process_files(
        self,
        processor_func: ProcessorFunc,
        filter_func: Optional[FilterFunc] = None,
        preserve_timestamps: bool = True,
    ) -> int:
        processed_count = 0
        if self.format_type == "single":
            data = self._read_single_file()
            filename = self.archive_path.stem
            if filter_func is None or filter_func(filename):
                processed_data = processor_func(data, filename)
                self._write_single_file(processed_data)
                processed_count = 1
        else:
            temp_dir = tempfile.mkdtemp(prefix="archive_processing_")
            try:
                processed_count = self._process_archive_files(
                    processor_func, filter_func, temp_dir, preserve_timestamps
                )
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)
        return processed_count

    def _read_single_file(self) -> bytes:
        with open(self.archive_path, "rb") as f:
            compressed_data = f.read()
        return self._decompress_data(compressed_data, self.compression)

    def _write_single_file(self, data: bytes) -> None:
        compressed_data = self._compress_data(data, self.compression)
        temp_path = self.archive_path.with_suffix(self.archive_path.suffix + ".tmp")
        with open(temp_path, "wb") as f:
            f.write(compressed_data)
        os.replace(temp_path, self.archive_path)

    def _process_archive_files(
        self,
        processor_func: ProcessorFunc,
        filter_func: Optional[FilterFunc],
        temp_dir: str,
        preserve_timestamps: bool,
    ) -> int:
        if self.format_type == "zip":
            return self._process_zip(processor_func, filter_func, temp_dir, preserve_timestamps)
        if self.format_type == "tar":
            return self._process_tar(processor_func, filter_func, temp_dir, preserve_timestamps)
        if self.format_type == "7zip":
            return self._process_7zip(processor_func, filter_func, temp_dir, preserve_timestamps)
        raise UnsupportedFormatError(f"Unsupported archive type: {self.format_type}")

    def _process_zip(
        self,
        processor_func: ProcessorFunc,
        filter_func: Optional[FilterFunc],
        temp_dir: str,
        preserve_timestamps: bool,
    ) -> int:
        processed_count = 0
        temp_archive_path = os.path.join(temp_dir, "archive.zip")
        with zipfile.ZipFile(self.archive_path, "r") as src_zip, zipfile.ZipFile(temp_archive_path, "w") as dst_zip:
            for item in src_zip.infolist():
                data = src_zip.read(item.filename)
                filename = item.filename
                if filter_func is None or filter_func(filename):
                    try:
                        data = processor_func(data, filename)
                        processed_count += 1
                    except Exception as e:
                        print(f"Warning: Failed to process {filename}: {e}")
                if preserve_timestamps:
                    dst_zip.writestr(item, data)
                else:
                    dst_zip.writestr(filename, data)
        os.replace(temp_archive_path, self.archive_path)
        return processed_count

    def _process_tar(
        self,
        processor_func: ProcessorFunc,
        filter_func: Optional[FilterFunc],
        temp_dir: str,
        preserve_timestamps: bool,
    ) -> int:
        processed_count = 0
        temp_archive_path = os.path.join(temp_dir, "archive.tar")
        write_mode = self._tar_write_mode()
        with (
            tarfile.open(self.archive_path, self._tar_read_mode()) as src_tar,
            tarfile.open(temp_archive_path, write_mode) as dst_tar,
        ):
            for member in src_tar.getmembers():
                if member.isfile():
                    extracted = src_tar.extractfile(member)
                    if extracted is None:
                        
                        continue
                    with extracted:
                        data = extracted.read()
                    if filter_func is None or filter_func(member.name):
                        try:
                            data = processor_func(data, member.name)
                            processed_count += 1
                        except Exception as e:
                            print(f"Warning: Failed to process {member.name}: {e}")
                    member.size = len(data)
                    if preserve_timestamps:
                        dst_tar.addfile(member, io.BytesIO(data))
                    else:
                        new_member = tarfile.TarInfo(name=member.name)
                        new_member.size = len(data)
                        new_member.mode = member.mode
                        dst_tar.addfile(new_member, io.BytesIO(data))
                else:
                    dst_tar.addfile(member)
        os.replace(temp_archive_path, self.archive_path)
        return processed_count

    def _process_7zip(
        self,
        processor_func: ProcessorFunc,
        filter_func: Optional[FilterFunc],
        temp_dir: str,
        preserve_timestamps: bool,
    ) -> int:
        import py7zr

        processed_count = 0
        temp_archive_path = os.path.join(temp_dir, "archive.7z")
        with py7zr.SevenZipFile(self.archive_path, "r") as src_7z:
            all_files = src_7z.getnames()
            src_7z.extractall(path=temp_dir)
        for filename in all_files:
            file_path = os.path.join(temp_dir, filename)
            if os.path.isfile(file_path):
                with open(file_path, "rb") as f:
                    data = f.read()
                if filter_func is None or filter_func(filename):
                    try:
                        data = processor_func(data, filename)
                        processed_count += 1
                        with open(file_path, "wb") as f:
                            f.write(data)
                    except Exception as e:
                        print(f"Warning: Failed to process {filename}: {e}")
        with py7zr.SevenZipFile(temp_archive_path, "w") as dst_7z:
            for filename in all_files:
                file_path = os.path.join(temp_dir, filename)
                if os.path.isfile(file_path):
                    dst_7z.write(file_path, filename)
        os.replace(temp_archive_path, self.archive_path)
        return processed_count


def process_archive(
    archive_path: Union[str, os.PathLike[str]],
    processor_func: ProcessorFunc,
    filter_func: Optional[FilterFunc] = None,
    preserve_timestamps: bool = True,
) -> int:
    processor = ArchiveProcessor(archive_path)
    return processor.process_files(processor_func, filter_func, preserve_timestamps)
