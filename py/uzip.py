from pathlib import Path
import argparse
import os
import pathlib
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime
from stat import S_IFLNK

APP_UNZIP = os.environ.get("MC_TEST_EXTFS_LIST_CMD") or "/data/data/com.termux/files/usr/bin/unzip"
APP_ZIP = "/data/data/com.termux/files/usr/bin/zip"


def croak(command: str, desc: str | None = None, exit_code=1):
    if desc:
        sys.stderr.write(f"uzip ({sys.argv[1]}): {command} - {desc}\n")
    else:
        sys.stderr.write(f"uzip ({sys.argv[1]}): {command} - {os.strerror(os.errno)}\n")
    sys.exit(exit_code)


def absolutize(filepath, cwd: Path):
    if not pathlib.Path(filepath).is_absolute():
        return os.path.join(cwd, filepath)
    return filepath


def zipfs_canonicalize_pathname(fname: str):
    return os.path.normpath(fname).replace("\\", "/")


def safesystem(command: str, *allow_rc) -> None:
    import subprocess

    try:
        result = subprocess.run(
            command,
            shell=True,
            check=False,
            text=True,
            capture_output=True,
        )
    except Exception as e:
        croak(
            f"subprocess run failed for: {command}",
            str(e),
        )
    if result.returncode != 0 and result.returncode not in allow_rc:
        cmd_name = command.split()[0]
        desc = result.stderr.strip() or f"non-zero exit status ({result.returncode})"
        croak(
            f"`{cmd_name}' failed",
            desc,
            exit_code=result.returncode,
        )


def get_link_destination(archive_path, link_name) -> str:
    cmd = f"{APP_UNZIP} -p {archive_path} {link_name}"
    import subprocess

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            check=True,
            text=True,
            capture_output=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        croak(
            f"External unzip failed to get link destination for {link_name}",
            str(e),
        )
    except FileNotFoundError:
        croak(
            "Required command 'unzip' not found",
            f"Please ensure {APP_UNZIP} exists.",
        )


def mczipfs_list(archive) -> None:
    try:
        with zipfile.ZipFile(archive, "r") as zf:
            infolist = sorted(
                zf.infolist(),
                key=lambda i: i.filename,
            )
    except FileNotFoundError:
        croak(f"Archive not found: {archive}")
    except zipfile.BadZipFile:
        croak(f"Bad or unreadable zip file: {archive}")
    file_data = {}
    for info in infolist:
        if info.external_attr:
            perms = info.external_attr >> 16
        else:
            perms = 0o644
        filename = info.filename
        is_dir = filename.endswith("/")
        if is_dir:
            perms_str = "drwxr-xr-x"
        elif perms & S_IFLNK:
            perms_str = "lrwxr-xr-x"
        else:
            perms_str = "-rw-r--r--"
        (perms & 0o777 if (perms & S_IFMT(perms)) else (0o755 if is_dir else 0o644))
        perms_mc = f"{perms_str}"
        date_time = datetime(*info.date_time)
        year, mon, day = (
            date_time.year,
            date_time.month,
            date_time.day,
        )
        hour, minute, sec = (
            date_time.hour,
            date_time.minute,
            date_time.second,
        )
        realsize = info.file_size
        file_data[filename] = {
            "perms_mc": perms_mc,
            "realsize": realsize,
            "mon": mon,
            "day": day,
            "year": year,
            "hour": hour,
            "min": minute,
            "sec": sec,
            "filename": filename,
            "is_link": perms & S_IFLNK,
        }
    for filename in sorted(file_data.keys()):
        data = file_data[filename]
        output_line = (
            f"{data['perms_mc']:<10}    1 {1:<8} {1:<8} {data['realsize']:>8} "
            f"{data['mon']}/{data['day']}/{data['year']} "
            f"{data['hour']:02}:{data['min']:02}:{data['sec']:02} ./{data['filename']}"
        )
        if data["is_link"]:
            link_dest = get_link_destination(archive, data["filename"])
            output_line += f" -> {link_dest}"
        print(output_line)


def mczipfs_rm(archive, filename: str) -> None:
    tmpfd, tmpname = tempfile.mkstemp(dir=pathlib.Path(archive).parent)
    os.close(tmpfd)
    filename_canonical = zipfs_canonicalize_pathname(filename)
    try:
        with zipfile.ZipFile(archive, "r") as zf_in:
            with zipfile.ZipFile(tmpname, "w", zipfile.ZIP_DEFLATED) as zf_out:
                for item in zf_in.infolist():
                    item_canonical = zipfs_canonicalize_pathname(item.filename)
                    if item_canonical != filename_canonical:
                        zf_out.writestr(
                            item,
                            zf_in.read(item.filename),
                        )
        shutil.move(tmpname, archive)
    except Exception as e:
        pathlib.Path(tmpname).unlink()
        croak(
            "Failed to delete file from zip",
            str(e),
        )


def mczipfs_rmdir(archive, directory: str) -> None:
    directory_canonical = zipfs_canonicalize_pathname(directory)
    if not directory_canonical.endswith("/"):
        directory_canonical += "/"
    tmpfd, tmpname = tempfile.mkstemp(dir=pathlib.Path(archive).parent)
    os.close(tmpfd)
    try:
        with zipfile.ZipFile(archive, "r") as zf_in:
            for item in zf_in.infolist():
                item_canonical = zipfs_canonicalize_pathname(item.filename)
                if item_canonical.startswith(directory_canonical) and item_canonical != directory_canonical:
                    croak(
                        "Directory is not empty",
                        f"Cannot delete non-empty directory: {directory}",
                    )
            with zipfile.ZipFile(tmpname, "w", zipfile.ZIP_DEFLATED) as zf_out:
                found = False
                for item in zf_in.infolist():
                    item_canonical = zipfs_canonicalize_pathname(item.filename)
                    if item_canonical != directory_canonical:
                        zf_out.writestr(
                            item,
                            zf_in.read(item.filename),
                        )
                    else:
                        found = True
                if not found:
                    pass
        shutil.move(tmpname, archive)
    except Exception as e:
        if pathlib.Path(tmpname).exists():
            pathlib.Path(tmpname).unlink()
        croak(
            "Failed to delete directory from zip",
            str(e),
        )


def mczipfs_copyout(archive, archive_file: str, local_file: str) -> None:
    archive_file_canonical = zipfs_canonicalize_pathname(archive_file)
    try:
        with zipfile.ZipFile(archive, "r") as zf:
            zf.extract(
                archive_file_canonical,
                path=pathlib.Path(local_file).parent,
            )
            extracted_path = os.path.join(
                pathlib.Path(local_file).parent,
                archive_file_canonical,
            )
            if pathlib.Path(extracted_path).exists():
                shutil.move(extracted_path, local_file)
            else:
                shutil.move(
                    pathlib.Path(archive_file_canonical).name,
                    local_file,
                )
    except KeyError:
        croak(
            "File not found in archive",
            f"{archive_file}",
        )
    except Exception as e:
        croak("Failed to copy out file", str(e))


def mczipfs_copyin(archive, archive_file: str, local_file: str) -> None:
    cwd = pathlib.Path.cwd()
    abs_local_file = absolutize(local_file, cwd)
    archive_file_canonical = zipfs_canonicalize_pathname(archive_file)
    tmpdir = tempfile.mkdtemp()
    tmpname = os.path.join(tmpdir, "temp_archive.zip")
    try:
        with zipfile.ZipFile(archive, "r") as zf_in:
            with zipfile.ZipFile(tmpname, "w", zipfile.ZIP_DEFLATED) as zf_out:
                for item in zf_in.infolist():
                    item_canonical = zipfs_canonicalize_pathname(item.filename)
                    if item_canonical != archive_file_canonical:
                        zf_out.writestr(
                            item,
                            zf_in.read(item.filename),
                        )
        with zipfile.ZipFile(tmpname, "a", zipfile.ZIP_DEFLATED) as zf_append:
            zf_append.write(
                abs_local_file,
                arcname=archive_file_canonical,
            )
        shutil.move(tmpname, archive)
    except FileNotFoundError:
        croak("Local file not found", abs_local_file)
    except Exception as e:
        croak("Failed to copy in file", str(e))
    finally:
        shutil.rmtree(tmpdir)


def mczipfs_mkdir(archive, directory: str) -> None:
    directory_canonical = zipfs_canonicalize_pathname(directory)
    if not directory_canonical.endswith("/"):
        directory_canonical += "/"
    try:
        with zipfile.ZipFile(archive, "a", zipfile.ZIP_DEFLATED) as zf:
            zi = zipfile.ZipInfo(directory_canonical)
            zi.external_attr = (0o40775 << 16) | 0x10
            zi.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(zi, "")
    except Exception as e:
        croak("Failed to create directory", str(e))


def mczipfs_run(archive, archive_file: str) -> None:
    archive_file_canonical = zipfs_canonicalize_pathname(archive_file)
    tmpdir = tempfile.mkdtemp()
    tmpfile = os.path.join(
        tmpdir,
        pathlib.Path(archive_file_canonical).name,
    )
    try:
        safesystem(f"{APP_UNZIP} -p {archive} {archive_file_canonical} > {tmpfile}")
        pathlib.Path(tmpfile).chmod(0o700)
        safesystem(f"cd {tmpdir} && ./{pathlib.Path(tmpfile).name}")
    except Exception as e:
        croak("Failed to run file", str(e))
    finally:
        shutil.rmtree(tmpdir)


def mczipfs_mklink(archive, link_dest: str, archive_file: str) -> None:
    archive_file_canonical = zipfs_canonicalize_pathname(archive_file)
    tmpdir = tempfile.mkdtemp()
    tmp_link_path = os.path.join(
        tmpdir,
        pathlib.Path(archive_file_canonical).name,
    )
    try:
        pathlib.Path(tmp_link_path).write_text(link_dest, encoding="utf-8")
        with zipfile.ZipFile(archive, "a", zipfile.ZIP_DEFLATED) as zf_append:
            zi = zipfile.ZipInfo(archive_file_canonical)
            zi.external_attr = 0o120777 << 16
            zi.compress_type = zipfile.ZIP_DEFLATED
            with pathlib.Path(tmp_link_path).open("rb") as f_in:
                zf_append.writestr(zi, f_in.read())
    except Exception as e:
        croak(
            "Failed to create symbolic link",
            str(e),
        )
    finally:
        shutil.rmtree(tmpdir)


def mczipfs_linkout(archive, archive_file: str, local_file: str) -> None:
    archive_file_canonical = zipfs_canonicalize_pathname(archive_file)
    try:
        link_dest = get_link_destination(archive, archive_file_canonical)
        pathlib.Path(local_file).symlink_to(link_dest)
    except Exception as e:
        croak("Failed to create local link", str(e))


if __name__ == "__main__":
    OLD_PWD = pathlib.Path.cwd()
    parser = argparse.ArgumentParser(description="Python ZIP FS wrapper for external use (e.g., Midnight Commander).")
    parser.add_argument(
        "command",
        choices=[
            "list",
            "rm",
            "rmdir",
            "mkdir",
            "copyin",
            "copyout",
            "run",
            "mklink",
            "linkout",
        ],
        help="The operation to perform.",
    )
    parser.add_argument(
        "archive",
        help="The path to the ZIP archive.",
    )
    args, unknown = parser.parse_known_args()
    cmd = args.command
    archive = args.archive
    aarchive = absolutize(archive, OLD_PWD)
    if cmd == "list":
        mczipfs_list(aarchive)
    elif cmd == "rm":
        if len(unknown) < 1:
            croak("missing argument", "archive file")
        mczipfs_rm(aarchive, unknown[0])
    elif cmd == "rmdir":
        if len(unknown) < 1:
            croak(
                "missing argument",
                "archive directory",
            )
        mczipfs_rmdir(aarchive, unknown[0])
    elif cmd == "mkdir":
        if len(unknown) < 1:
            croak("missing argument", "directory")
        mczipfs_mkdir(aarchive, unknown[0])
    elif cmd == "copyin":
        if len(unknown) < 2:
            croak(
                "missing argument",
                "archive file and local file",
            )
        mczipfs_copyin(aarchive, unknown[0], unknown[1])
    elif cmd == "copyout":
        if len(unknown) < 2:
            croak(
                "missing argument",
                "archive file and local file",
            )
        mczipfs_copyout(aarchive, unknown[0], unknown[1])
    elif cmd == "run":
        if len(unknown) < 1:
            croak("missing argument", "archive file")
        mczipfs_run(aarchive, unknown[0])
    elif cmd == "mklink":
        if len(unknown) < 2:
            croak(
                "missing argument",
                "link destination and archive file",
            )
        mczipfs_mklink(aarchive, unknown[0], unknown[1])
    elif cmd == "linkout":
        if len(unknown) < 2:
            croak(
                "missing argument",
                "archive file and local file",
            )
        mczipfs_linkout(aarchive, unknown[0], unknown[1])
    else:
        croak(
            "Unknown command",
            f"Command '{cmd}' is not recognized.",
        )
    sys.exit(0)
