from __future__ import annotations

import os
import gzip
import bz2
import lzma
import brotli
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

import zstandard as zstd  
import lz4.frame  
import py7zr  



CHUNK = 1024 * 1024  
XZ_PRESET_9 = 9  





def human_bytes(n: int) -> str:
    sign = "-" if n < 0 else ""
    n = abs(n)
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    return f"{sign}{n:.2f} {units[i]}" if units[i] != "B" else f"{sign}{int(n)} B"


def dir_files_total_bytes(p: Path) -> int:
    total = 0
    for x in p.iterdir():
        if x.is_file():
            total += x.stat().st_size
    return total


def decode_filename_to_tar_path(src: Path) -> Path:
    
    
    return Path(str(src)[: -len("." + src.suffixes[-1])])  


def tar_stem_and_codec(p: Path) -> tuple[str, str] | None:
    parts = p.name.split(".")
    if len(parts) < 3:
        return None
    if parts[-2] != "tar":
        return None
    codec = parts[-1].lower()
    stem = ".".join(parts[:-2])
    if not stem:
        stem = "archive"
    return stem, codec


def tar_output_from_codec(stem: str, codec: str) -> Path:
    return Path(f"{stem}.tar.{codec}")


def safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass





def open_tar_bytes_reader(src: Path):
    return src


def write_tar_bytes_with_decoder_to_file(src: Path, dst: Path, codec: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)

    if codec == "gz":
        with gzip.open(src, "rb") as f_in, dst.open("wb") as f_out:
            while True:
                chunk = f_in.read(CHUNK)
                if not chunk:
                    break
                f_out.write(chunk)

    elif codec == "bz2":
        with bz2.open(src, "rb") as f_in, dst.open("wb") as f_out:
            while True:
                chunk = f_in.read(CHUNK)
                if not chunk:
                    break
                f_out.write(chunk)

    elif codec == "xz":
        with lzma.open(src, "rb", format=lzma.FORMAT_XZ) as f_in, dst.open("wb") as f_out:
            while True:
                chunk = f_in.read(CHUNK)
                if not chunk:
                    break
                f_out.write(chunk)

    elif codec == "zst":
        dctx = zstd.ZstdDecompressor()
        with src.open("rb") as f_in:
            with dctx.stream_reader(f_in) as zreader, dst.open("wb") as f_out:
                while True:
                    chunk = zreader.read(CHUNK)
                    if not chunk:
                        break
                    f_out.write(chunk)

    elif codec == "br":
        
        
        dec = brotli.Decompressor()
        with src.open("rb") as f_in, dst.open("wb") as f_out:
            while True:
                data = f_in.read(CHUNK)
                if not data:
                    break
                f_out.write(dec.process(data))
            f_out.write(dec.finish())

    elif codec == "lz4":
        with lz4.frame.open(src, "rb") as f_in, dst.open("wb") as f_out:
            while True:
                chunk = f_in.read(CHUNK)
                if not chunk:
                    break
                f_out.write(chunk)

    else:
        raise ValueError(f"Unsupported codec for tar bytes decoding: {codec}")


def write_compressed_tar_bytes_from_tar(src_tar: Path, dst: Path, codec: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)

    if codec == "gz":
        with src_tar.open("rb") as f_in, gzip.open(dst, "wb", compresslevel=9) as f_out:
            while True:
                chunk = f_in.read(CHUNK)
                if not chunk:
                    break
                f_out.write(chunk)

    elif codec == "bz2":
        
        
        compressor = bz2.BZ2Compressor(compresslevel=9)
        with src_tar.open("rb") as f_in, dst.open("wb") as f_out:
            while True:
                chunk = f_in.read(CHUNK)
                if not chunk:
                    break
                out = compressor.compress(chunk)
                if out:
                    f_out.write(out)
            tail = compressor.flush()
            if tail:
                f_out.write(tail)

    elif codec == "xz":
        comp = lzma.LZMACompressor(format=lzma.FORMAT_XZ, check=-1, preset=XZ_PRESET_9)
        with src_tar.open("rb") as f_in, dst.open("wb") as f_out:
            while True:
                chunk = f_in.read(CHUNK)
                if not chunk:
                    break
                out = comp.compress(chunk)
                if out:
                    f_out.write(out)
            tail = comp.flush()
            if tail:
                f_out.write(tail)

    elif codec == "zst":
        cctx = zstd.ZstdCompressor(level=22)
        with src_tar.open("rb") as f_in, dst.open("wb") as f_out:
            with cctx.stream_writer(f_out) as zw:
                while True:
                    chunk = f_in.read(CHUNK)
                    if not chunk:
                        break
                    zw.write(chunk)

    elif codec == "br":
        
        
        compressor = brotli.Compressor(quality=11)
        with src_tar.open("rb") as f_in, dst.open("wb") as f_out:
            while True:
                chunk = f_in.read(CHUNK)
                if not chunk:
                    break
                out = compressor.process(chunk)
                if out:
                    f_out.write(out)
            tail = compressor.finish()
            if tail:
                f_out.write(tail)

    elif codec == "lz4":
        comp = lz4.frame.LZ4FrameCompressor(block_size=lz4.frame.BLOCKSIZE_MAX)
        with src_tar.open("rb") as f_in, dst.open("wb") as f_out:
            while True:
                chunk = f_in.read(CHUNK)
                if not chunk:
                    break
                out = comp.compress(chunk)
                if out:
                    f_out.write(out)
            tail = comp.flush()
            if tail:
                f_out.write(tail)

    else:
        raise ValueError(f"Unsupported codec for tar bytes encoding: {codec}")







def convert_tar7z_via_py7zr(src: Path, dst: Path) -> None:
    
    
    
    import tempfile

    tmpdir = Path(tempfile.mkdtemp(prefix="tar7z_conv_"))
    try:
        tar_path = tmpdir / (src.stem + ".tar")  
        with py7zr.SevenZipFile(src, mode="r") as z:
            z.extractall(path=tmpdir)
        
        extracted = next(tmpdir.glob("*.tar"), None)
        if extracted is None:
            
            files = [p for p in tmpdir.rglob("*") if p.is_file()]
            if not files:
                raise RuntimeError("No files extracted from .tar.7z")
            extracted = files[0]
        tmp_tar = extracted
        
        codec = dst.suffixes[-1].lower()
        write_compressed_tar_bytes_from_tar(tmp_tar, dst, codec)
    finally:
        shutil_rmtree_quiet(tmpdir)


def shutil_rmtree_quiet(p: Path) -> None:
    try:
        if p.exists():
            import shutil

            shutil.rmtree(p)
    except Exception:
        pass




SUPPORTED = {"gz", "zst", "xz", "bz2", "lz4", "br", "7z"}




def convert_one_task(src_str: str, dst_codec: str) -> tuple[str, str, bool, str, int]:
    import traceback

    src = Path(src_str)
    parse = tar_stem_and_codec(src)
    if not parse:
        return (src.name, "", False, "Not in form *.tar.<codec>", 0)
    stem, src_codec = parse
    dst = tar_output_from_codec(stem, dst_codec)

    if dst.exists():
        return (src.name, dst.name, True, f"skipped (exists): {dst.name}", 0)

    
    
    
    tmp_tar = Path(f".__tmp_tar_conv_{os.getpid()}_{stem}.tar")

    try:
        
        if src_codec == "7z":
            
            import tempfile

            tmpdir = Path(tempfile.mkdtemp(prefix="tar7z_dec_"))
            try:
                with py7zr.SevenZipFile(src, mode="r") as z:
                    z.extractall(path=tmpdir)
                extracted = next(tmpdir.glob("*.tar"), None)
                if extracted is None:
                    files = [p for p in tmpdir.rglob("*") if p.is_file()]
                    if not files:
                        raise RuntimeError("No files extracted from .tar.7z")
                    extracted = files[0]
                shutil_copyfile_quiet(extracted, tmp_tar)
            finally:
                shutil_rmtree_quiet(tmpdir)
        else:
            write_tar_bytes_with_decoder_to_file(src, tmp_tar, src_codec)

        
        if dst_codec == "7z":
            
            with py7zr.SevenZipFile(dst, mode="w") as z:
                z.write(tmp_tar, arcname=tmp_tar.name)
        else:
            write_compressed_tar_bytes_from_tar(tmp_tar, dst, dst_codec)

        
        src.unlink()
        return (src.name, dst.name, True, f"converted -> {dst.name} (removed original)", 0)
    except Exception as e:
        try:
            if dst.exists():
                dst.unlink()
        except Exception:
            pass
        return (src.name, dst.name, False, f"error: {e}\n{traceback.format_exc(limit=1)}", 0)
    finally:
        try:
            if tmp_tar.exists():
                tmp_tar.unlink()
        except Exception:
            pass


def shutil_copyfile_quiet(src: Path, dst: Path) -> None:
    import shutil

    shutil.copyfile(src, dst)


def guess_target_codecs(src_codec: str) -> list[str]:
    
    order = ["gz", "zst", "xz", "bz2", "7z", "lz4", "br"]
    return [c for c in order if c != src_codec]


def main() -> None:
    cwd = Path(".").resolve()

    files = [
        p
        for p in cwd.glob("*.tar.*")
        if len(p.suffixes) >= 2 and p.suffixes[-2] == ".tar" or p.name.endswith(".tar." + p.suffixes[-1])
    ]
    
    tar_inputs = []
    for p in cwd.iterdir():
        if not p.is_file():
            continue
        parse = tar_stem_and_codec(p)
        if not parse:
            continue
        _, codec = parse
        if codec in SUPPORTED:
            tar_inputs.append(p)

    tar_inputs = sorted(tar_inputs)
    if not tar_inputs:
        print("No *.tar.<codec> files found in current directory.")
        return

    initial_bytes = dir_files_total_bytes(cwd)

    max_workers = max(1, min(os.cpu_count() or 1, len(tar_inputs)))
    results = []

    
    
    target_set = {"gz", "zst", "bz2", "lz4", "7z", "br", "xz"}

    tasks = []
    with ProcessPoolExecutor(max_workers=max_workers) as ex:
        futures = []
        for src in tar_inputs:
            _, src_codec = tar_stem_and_codec(src)
            for dst_codec in sorted(target_set - {src_codec}):
                
                futures.append(ex.submit(convert_one_task, str(src), dst_codec))
        for f in as_completed(futures):
            results.append(f.result())

    final_bytes = dir_files_total_bytes(cwd)
    delta = final_bytes - initial_bytes

    ok_count = sum(1 for r in results if r[2])
    fail_count = len(results) - ok_count

    print(f"Converted tasks: {len(results)}; OK: {ok_count}; Failed/Skipped: {fail_count}")
    for src_name, dst_name, ok, msg, _ in sorted(results, key=lambda x: (x[0], x[1])):
        status = "OK" if ok else "FAIL"
        print(f"[{status}] {src_name} -> {dst_name}: {msg}")

    print(f"Disk usage (files in cwd) initial: {human_bytes(initial_bytes)}")
    print(f"Disk usage (files in cwd) final:   {human_bytes(final_bytes)}")
    if delta < 0:
        print(f"Saved: {human_bytes(-delta)}")
    elif delta > 0:
        print(f"Extra used: {human_bytes(delta)}")
    else:
        print("No disk usage change (by summed file sizes in cwd).")


if __name__ == "__main__":
    main()
