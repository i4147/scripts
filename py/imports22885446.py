import os
import sys
import ast
import zipfile
import tarfile
import subprocess
from pathlib import Path
from typing import Set, List, Tuple
from multiprocessing import Pool, cpu_count
from collections import defaultdict
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


class PythonImportExtractor:
    def __init__(self, pip_packages_file: str = "/sdcard/data/pip.txt"):
        self.pip_packages = self._load_pip_packages(pip_packages_file)
        self.stdlib_modules = self._get_stdlib_modules()
        self.local_modules = set()

    @staticmethod
    def _get_stdlib_modules() -> Set[str]:
        stdlib = set(sys.builtin_module_names)

        stdlib.update(
            {
                "abc",
                "aifc",
                "argparse",
                "array",
                "ast",
                "asynchat",
                "asyncio",
                "asyncore",
                "atexit",
                "audioop",
                "base64",
                "bdb",
                "binascii",
                "binhex",
                "bisect",
                "builtins",
                "bz2",
                "calendar",
                "cgi",
                "cgitb",
                "chunk",
                "cmath",
                "cmd",
                "code",
                "codecs",
                "codeop",
                "collections",
                "colorsys",
                "compileall",
                "concurrent",
                "configparser",
                "contextlib",
                "contextvars",
                "copy",
                "copyreg",
                "cProfile",
                "crypt",
                "csv",
                "ctypes",
                "curses",
                "dataclasses",
                "datetime",
                "dbm",
                "decimal",
                "difflib",
                "dis",
                "distutils",
                "doctest",
                "dummy_thread",
                "dummy_threading",
                "email",
                "encodings",
                "ensurepip",
                "enum",
                "errno",
                "faulthandler",
                "fcntl",
                "filecmp",
                "fileinput",
                "fnmatch",
                "formatter",
                "fractions",
                "ftplib",
                "functools",
                "gc",
                "getopt",
                "getpass",
                "gettext",
                "glob",
                "grp",
                "gzip",
                "hashlib",
                "heapq",
                "hmac",
                "html",
                "http",
                "idlelib",
                "imaplib",
                "imghdr",
                "imp",
                "importlib",
                "inspect",
                "io",
                "ipaddress",
                "itertools",
                "json",
                "keyword",
                "lib2to3",
                "linecache",
                "locale",
                "logging",
                "lzma",
                "mailbox",
                "mailcap",
                "marshal",
                "math",
                "mimetypes",
                "mmap",
                "modulefinder",
                "msilib",
                "msvcrt",
                "multiprocessing",
                "netrc",
                "nis",
                "nntplib",
                "numbers",
                "operator",
                "optparse",
                "os",
                "ossaudiodev",
                "parser",
                "pathlib",
                "pdb",
                "pickle",
                "pickletools",
                "pipes",
                "pkgutil",
                "platform",
                "plistlib",
                "poplib",
                "posix",
                "posixpath",
                "pprint",
                "profile",
                "pstats",
                "pty",
                "pwd",
                "py_compile",
                "pyclbr",
                "pydoc",
                "queue",
                "quopri",
                "random",
                "readline",
                "reprlib",
                "re",
                "resource",
                "rlcompleter",
                "runpy",
                "sched",
                "secrets",
                "select",
                "selectors",
                "shelve",
                "shlex",
                "shutil",
                "signal",
                "site",
                "smtpd",
                "smtplib",
                "sndhdr",
                "socket",
                "socketserver",
                "spwd",
                "sqlite3",
                "ssl",
                "stat",
                "statistics",
                "string",
                "stringprep",
                "struct",
                "subprocess",
                "sunau",
                "symbol",
                "symtable",
                "sys",
                "sysconfig",
                "syslog",
                "tabnanny",
                "tarfile",
                "telnetlib",
                "tempfile",
                "termios",
                "test",
                "textwrap",
                "threading",
                "time",
                "timeit",
                "tkinter",
                "token",
                "tokenize",
                "trace",
                "traceback",
                "tracemalloc",
                "tty",
                "turtle",
                "turtledemo",
                "types",
                "typing",
                "typing_extensions",
                "unicodedata",
                "unittest",
                "urllib",
                "uu",
                "uuid",
                "venv",
                "warnings",
                "wave",
                "weakref",
                "webbrowser",
                "winreg",
                "winsound",
                "wsgiref",
                "xdrlib",
                "xml",
                "xmlrpc",
                "zipapp",
                "zipfile",
                "zipimport",
                "zlib",
                "__future__",
                "__main__",
                "dataclasses",
                "graphlib",
                "tomllib",
                "zoneinfo",
            }
        )

        return stdlib

    @staticmethod
    def _load_pip_packages(pip_file: str) -> Set[str]:
        try:
            if not os.path.exists(pip_file):
                logger.warning(f"pip packages file not found: {pip_file}")
                return set()

            packages = set()
            with open(pip_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip().lower()
                    if line:
                        package_name = (
                            line.split("==")[0]
                            .split(">=")[0]
                            .split("<=")[0]
                            .split(">")[0]
                            .split("<")[0]
                            .split(";")[0]
                            .strip()
                        )
                        packages.add(package_name.replace("-", "_"))
                        packages.add(package_name.replace("_", "-"))
            logger.info(f"Loaded {len(packages)} pip packages")
            return packages
        except Exception as e:
            logger.error(f"Error loading pip packages: {e}")
            return set()

    @staticmethod
    def _extract_imports_from_ast(code: str, filename: str = "<string>") -> Set[str]:
        imports = set()
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module_name = alias.name.split(".")[0]
                        imports.add(module_name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        module_name = node.module.split(".")[0]
                        imports.add(module_name)
        except SyntaxError as e:
            logger.debug(f"Syntax error in {filename}: {e}")
        except Exception as e:
            logger.debug(f"Error parsing {filename}: {e}")

        return imports

    def _identify_local_modules(self, directory: str = ".") -> None:
        for root, dirs, files in os.walk(directory):
            dirs[:] = [
                d
                for d in dirs
                if d not in {".git", "__pycache__", ".venv", "venv", "env", ".egg-info", "dist", "build"}
            ]

            for file in files:
                if file.endswith((".py", ".pyw")) or (os.path.isfile(os.path.join(root, file)) and "." not in file):
                    module_name = file.replace(".py", "").replace(".pyw", "")
                    if module_name != "__init__":
                        self.local_modules.add(module_name)

    def extract_from_file(self, filepath: str) -> Set[str]:
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                code = f.read()
            return self._extract_imports_from_ast(code, filepath)
        except Exception as e:
            logger.debug(f"Error reading {filepath}: {e}")
            return set()

    def extract_from_zip(self, zippath: str) -> Set[str]:
        imports = set()
        try:
            with zipfile.ZipFile(zippath, "r") as zf:
                for info in zf.filelist:
                    if info.filename.endswith((".py", ".pyw")):
                        try:
                            code = zf.read(info.filename).decode("utf-8", errors="ignore")
                            imports.update(self._extract_imports_from_ast(code, info.filename))
                        except Exception as e:
                            logger.debug(f"Error reading {info.filename} from {zippath}: {e}")
        except Exception as e:
            logger.debug(f"Error processing zip {zippath}: {e}")

        return imports

    def extract_from_tar(self, tarpath: str) -> Set[str]:
        imports = set()
        try:
            with tarfile.open(tarpath, "r:*") as tf:
                for member in tf.getmembers():
                    if member.name.endswith((".py", ".pyw")) and member.isfile():
                        try:
                            f = tf.extractfile(member)
                            code = f.read().decode("utf-8", errors="ignore")
                            imports.update(self._extract_imports_from_ast(code, member.name))
                        except Exception as e:
                            logger.debug(f"Error reading {member.name} from {tarpath}: {e}")
        except Exception as e:
            logger.debug(f"Error processing tar {tarpath}: {e}")

        return imports

    def extract_from_whl(self, whlpath: str) -> Set[str]:
        return self.extract_from_zip(whlpath)

    def process_file(self, filepath: str) -> Set[str]:
        if filepath.endswith(".zip") or filepath.endswith(".whl"):
            return self.extract_from_zip(filepath)
        elif filepath.endswith((".tar.gz", ".tar.xz", ".tar.zst")):
            return self.extract_from_tar(filepath)
        elif filepath.endswith((".py", ".pyw")) or (os.path.isfile(filepath) and "." not in os.path.basename(filepath)):
            return self.extract_from_file(filepath)

        return set()

    def filter_packages(self, imports: Set[str]) -> Set[str]:
        pip_packages = set()

        for imp in imports:
            imp_lower = imp.lower()

            if imp in self.stdlib_modules or imp_lower in self.stdlib_modules:
                continue

            if imp in self.local_modules or imp_lower in self.local_modules:
                continue

            if imp_lower in self.pip_packages or imp.replace("_", "-") in self.pip_packages:
                pip_packages.add(imp_lower)

        return pip_packages


def find_python_files(directory: str = ".") -> List[str]:
    python_files = []

    for root, dirs, files in os.walk(directory):
        dirs[:] = [
            d for d in dirs if d not in {".git", "__pycache__", ".venv", "venv", "env", ".egg-info", "dist", "build"}
        ]

        for file in files:
            filepath = os.path.join(root, file)
            if os.path.islink(filepath):
                continue

            if file.endswith((".py", ".pyw")):
                python_files.append(filepath)
            elif "." not in file:
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        first_line = f.readline()
                        if first_line.startswith("#!") and "python" in first_line:
                            python_files.append(filepath)
                except:
                    pass
            elif file.endswith((".zip", ".whl", ".tar.gz", ".tar.xz", ".tar.zst")):
                python_files.append(filepath)

    return python_files


def process_single_file(args: Tuple[str, PythonImportExtractor]) -> Tuple[str, Set[str]]:
    filepath, extractor = args
    imports = extractor.process_file(filepath)
    filtered = extractor.filter_packages(imports)
    return filepath, filtered


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Create requirements.txt by inspecting Python files")
    parser.add_argument("-d", "--directory", default=".", help="Directory to scan (default: current directory)")
    parser.add_argument(
        "-o", "--output", default="requirements.txt", help="Output file name (default: requirements.txt)"
    )
    parser.add_argument(
        "-p",
        "--pip-file",
        default="/sdcard/data/pip.txt",
        help="Path to pip packages file (default: /sdcard/data/pip.txt)",
    )
    parser.add_argument(
        "--workers", type=int, default=cpu_count(), help=f"Number of worker processes (default: {cpu_count()})"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info(f"Scanning directory: {args.directory}")

    extractor = PythonImportExtractor(args.pip_file)

    logger.info("Identifying local modules...")
    extractor._identify_local_modules(args.directory)
    logger.info(f"Found {len(extractor.local_modules)} local modules")

    logger.info("Finding Python files...")
    python_files = find_python_files(args.directory)
    logger.info(f"Found {len(python_files)} Python files/archives")

    if not python_files:
        logger.warning("No Python files found")
        return

    logger.info(f"Processing files with {args.workers} workers...")
    all_packages = defaultdict(set)

    with Pool(args.workers) as pool:
        results = pool.map(process_single_file, [(f, extractor) for f in python_files])

    for filepath, packages in results:
        for package in packages:
            all_packages[package].add(filepath)

    sorted_packages = sorted(all_packages.keys())

    logger.info(f"Found {len(sorted_packages)} unique packages")

    with open(args.output, "w") as f:
        for package in sorted_packages:
            f.write(f"{package}\n")

    logger.info(f"Requirements written to {args.output}")

    if args.verbose:
        logger.info("\nPackages found:")
        for package in sorted_packages:
            sources = all_packages[package]
            logger.info(f"  {package} (found in {len(sources)} file(s))")


if __name__ == "__main__":
    main()
