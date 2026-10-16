from docopt import ParsedOptions
import ast
import logging
import os
import pathlib
import re
import sys
import traceback
from contextlib import contextmanager

import requests
from docopt import docopt
from pipreqs import __version__
from yarg import json2package
from yarg.exceptions import HTTPError

REGEXP = [
    re.compile(r"^import (.+)$"),
    re.compile(r"^from ((?!\.+).*?) import (?:.*)$"),
]
DEFAULT_EXTENSIONS = [".py", ".pyw"]
scan_noteboooks = False


class NbconvertNotInstalled(ImportError):
    default_message = "In order to scan jupyter notebooks, please install the nbconvert and ipython libraries"

    def __init__(self, message: str = default_message) -> None:
        super().__init__(message)


@contextmanager
def _open(filename=None, mode: str = "r"):
    if not filename or filename == "-":
        if not mode or "r" in mode:
            file = sys.stdin
        elif "w" in mode:
            file = sys.stdout
        else:
            msg = f"Invalid mode for file: {mode}"
            raise ValueError(msg)
    else:
        file = pathlib.Path(filename).open(mode)
    try:
        yield file
    finally:
        if file not in {sys.stdin, sys.stdout}:
            file.close()


def get_all_imports(path, encoding="utf-8", extra_ignore_dirs=None, follow_links=True):
    imports = set()
    raw_imports = set()
    candidates = []
    ignore_errors = False
    ignore_dirs = [
        ".hg",
        ".svn",
        ".git",
        ".tox",
        "__pycache__",
        "env",
        "venv",
        ".ipynb_checkpoints",
    ]
    if extra_ignore_dirs:
        ignore_dirs_parsed = [pathlib.Path(os.path.realpath(e)).name for e in extra_ignore_dirs]
        ignore_dirs.extend(ignore_dirs_parsed)
    extensions = get_file_extensions()
    walk = os.walk(path, followlinks=follow_links)
    for root, dirs, files in walk:
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        candidates.append(pathlib.Path(root).name)
        py_files = [file for file in files if file_ext_is_allowed(file, DEFAULT_EXTENSIONS)]
        candidates.extend([os.path.splitext(filename)[0] for filename in py_files])
        files = [fn for fn in files if file_ext_is_allowed(fn, extensions)]
        for file_name in files:
            file_name = os.path.join(root, file_name)
            contents = read_file_content(file_name, encoding)
            try:
                tree = ast.parse(contents)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        raw_imports.update(subnode.name for subnode in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        raw_imports.add(node.module)
            except Exception as exc:
                if ignore_errors:
                    traceback.print_exc(exc)
                    logging.warning(f"Failed on file: {file_name}")
                    continue
                logging.error(f"Failed on file: {file_name}")
                raise exc
    for name in [n for n in raw_imports if n]:
        cleaned_name, _, _ = name.partition(".")
        imports.add(cleaned_name)
    packages = imports - (set(candidates) & imports)
    logging.debug("Found packages: %s", packages)
    with pathlib.Path(join("stdlib")).open(encoding="utf-8") as f:
        data = {x.strip() for x in f}
    return list(packages - data)


def get_file_extensions() -> list[str]:
    return [*DEFAULT_EXTENSIONS, ".ipynb"] if scan_noteboooks else DEFAULT_EXTENSIONS


def read_file_content(file_name: str, encoding="utf-8"):
    if file_ext_is_allowed(file_name, DEFAULT_EXTENSIONS):
        contents = pathlib.Path(file_name).read_text(encoding=encoding)
    elif file_ext_is_allowed(file_name, [".ipynb"]) and scan_noteboooks:
        contents = ipynb_2_py(file_name, encoding=encoding)
    return contents


def file_ext_is_allowed(file_name: str, acceptable: list[str]):
    return os.path.splitext(file_name)[1] in acceptable


def ipynb_2_py(file_name: str, encoding="utf-8"):
    exporter = PythonExporter()
    body, _ = exporter.from_filename(file_name)
    return body.encode(encoding)


def generate_requirements_file(path, imports, symbol: str) -> None:
    with _open(path, "w") as out_file:
        logging.debug(
            "Writing {num} requirements: {imports} to {file}".format(
                num=len(imports),
                file=path,
                imports=", ".join([x["name"] for x in imports]),
            )
        )
        fmt = "{name}" + symbol + "{version}"
        out_file.write(
            "\n".join(fmt.format(**item) if item["version"] else "{name}".format(**item) for item in imports) + "\n"
        )


def output_requirements(imports, symbol: str) -> None:
    generate_requirements_file("-", imports, symbol)


def get_imports_info(imports, pypi_server="https://pypi.python.org/pypi/", proxy=None):
    result = []
    for item in imports:
        try:
            logging.warning(
                'Import named "%s" not found locally. Trying to resolve it at the PyPI server.',
                item,
            )
            response = requests.get(f"{pypi_server}{item}/json", proxies=proxy)
            if response.status_code == 200:
                if hasattr(response.content, "decode"):
                    data = json2package(response.content.decode())
                else:
                    data = json2package(response.content)
            elif response.status_code >= 300:
                raise HTTPError(status_code=response.status_code, reason=response.reason)
        except HTTPError:
            logging.warning('Package "%s" does not exist or network problems', item)
            continue
        logging.warning(
            'Import named "%s" was resolved to "%s:%s" package (%s).\n'
            "Please, verify manually the final list of requirements.txt "
            "to avoid possible dependency confusions.",
            item,
            data.name,
            data.latest_release_id,
            data.pypi_url,
        )
        result.append({"name": item, "version": data.latest_release_id})
    return result


def get_locally_installed_packages(encoding: str = "utf-8"):
    packages = []
    ignore = ["tests", "_tests", "egg", "EGG", "info"]
    for path in sys.path:
        for root, _dirs, files in os.walk(path):
            for item in files:
                if "top_level" in item:
                    item = os.path.join(root, item)
                    with pathlib.Path(item).open(encoding=encoding) as f:
                        package = root.split(os.sep)[-1].split("-")
                        try:
                            top_level_modules = f.read().strip().split("\n")
                        except:
                            continue
                        filtered_top_level_modules = [
                            module
                            for module in top_level_modules
                            if (module not in ignore) and (package[0] not in ignore)
                        ]
                        version = None
                        if len(package) > 1:
                            version = package[1].replace(".dist", "").replace(".egg", "")
                        packages.append({
                            "name": package[0],
                            "version": version,
                            "exports": filtered_top_level_modules,
                        })
    return packages


def get_import_local(imports, encoding="utf-8"):
    local = get_locally_installed_packages()
    result = []
    for item in imports:
        result.extend(package for package in local if item in package["exports"] or item == package["name"])
    return [i for n, i in enumerate(result) if i not in result[n + 1 :]]


def get_pkg_names(pkgs):
    result = set()
    with pathlib.Path(join("mapping")).open(encoding="utf-8") as f:
        data = dict(x.strip().split(":") for x in f)
    result.update(data.get(pkg, pkg) for pkg in pkgs)
    return sorted(result, key=lambda s: s.lower())


def get_name_without_alias(name):
    if "import " in name:
        match = REGEXP[0].match(name.strip())
        if match:
            name = match.groups(0)[0]
    return name.partition(" as ")[0].partition(".")[0].strip()


def join(f: str) -> str:
    return os.path.join(pathlib.Path(__file__).parent, f)


def parse_requirements(file_):
    modules = []
    delim = ["<", ">", "=", "!", "~"]
    try:
        f = pathlib.Path(file_).open(encoding="utf-8")
    except FileNotFoundError:
        print(f"File {file_} was not found. Please, fix it and run again.")
        sys.exit(1)
    except OSError as error:
        logging.error(f"There was an error opening the file {file_}: {error!s}")
        raise error
    else:
        try:
            data = [x.strip() for x in f if x != "\n"]
        finally:
            f.close()
    data = [x for x in data if x[0].isalpha()]
    for x in data:
        if not any(y in x for y in delim):
            modules.append({"name": x, "version": None})
        for y in x:
            if y in delim:
                module = x.split(y)
                module_name = module[0]
                module_version = module[-1].replace("=", "")
                module = {"name": module_name, "version": module_version}
                if module not in modules:
                    modules.append(module)
                break
    return modules


def compare_modules(file_, imports):
    modules = parse_requirements(file_)
    imports = [imports[i]["name"] for i in range(len(imports))]
    modules = [modules[i]["name"] for i in range(len(modules))]
    return set(modules) - set(imports)


def diff(file_, imports) -> None:
    modules_not_imported = compare_modules(file_, imports)
    logging.info(
        "The following modules are in {} but do not seem to be imported: {}".format(
            file_, ", ".join(x for x in modules_not_imported)
        )
    )


def clean(file_, imports) -> None:
    modules_not_imported = compare_modules(file_, imports)
    if len(modules_not_imported) == 0:
        logging.info("Nothing to clean in " + file_)
        return
    re_remove = re.compile("|".join(modules_not_imported))
    to_write = []
    try:
        f = pathlib.Path(file_).open("r+", encoding="utf-8")
    except OSError:
        logging.error("Failed on file: %s", file_)
        raise
    else:
        try:
            to_write.extend(i for i in f if re_remove.match(i) is None)
            f.seek(0)
            f.truncate()
            f.writelines(to_write)
        finally:
            f.close()
    logging.info("Successfully cleaned up requirements in " + file_)


def dynamic_versioning(scheme: str, imports):
    if scheme == "no-pin":
        imports = [{"name": item["name"], "version": ""} for item in imports]
        symbol = ""
    elif scheme == "gt":
        symbol = ">="
    elif scheme == "compat":
        symbol = "~="
    return imports, symbol


def handle_scan_noteboooks() -> None:
    if not scan_noteboooks:
        logging.info("Not scanning for jupyter notebooks.")
        return
    try:
        global PythonExporter
        from nbconvert import PythonExporter
    except ImportError:
        raise NbconvertNotInstalled


def init(args: ParsedOptions) -> None:
    global scan_noteboooks
    encoding = args.get("--encoding")
    extra_ignore_dirs = args.get("--ignore")
    follow_links = not args.get("--no-follow-links")
    scan_noteboooks = args.get("--scan-notebooks", False)
    handle_scan_noteboooks()
    input_path = args["<path>"]
    if encoding is None:
        encoding = "utf-8"
    if input_path is None:
        input_path = pathlib.Path(os.curdir).resolve()
    if extra_ignore_dirs:
        extra_ignore_dirs = extra_ignore_dirs.split(",")
    path = args["--savepath"] or os.path.join(input_path, "requirements.txt")
    if not args["--print"] and not args["--savepath"] and not args["--force"] and pathlib.Path(path).exists():
        logging.warning("requirements.txt already exists, use --force to overwrite it")
        return
    candidates = get_all_imports(
        input_path,
        encoding=encoding,
        extra_ignore_dirs=extra_ignore_dirs,
        follow_links=follow_links,
    )
    candidates = get_pkg_names(candidates)
    logging.debug("Found imports: " + ", ".join(candidates))
    pypi_server = "https://pypi.python.org/pypi/"
    proxy = None
    if args["--pypi-server"]:
        pypi_server = args["--pypi-server"]
    if args["--proxy"]:
        proxy = {"http": args["--proxy"], "https": args["--proxy"]}
    if args["--use-local"]:
        logging.debug("Getting package information ONLY from local installation.")
        imports = get_import_local(candidates, encoding=encoding)
    else:
        logging.debug("Getting packages information from Local/PyPI")
        local = get_import_local(candidates, encoding=encoding)
        difference = [
            x
            for x in candidates
            if x.lower() not in [y for x in local for y in x["exports"]] and x.lower() not in [x["name"] for x in local]
        ]
        imports = local + get_imports_info(difference, proxy=proxy, pypi_server=pypi_server)
    imports = sorted(imports, key=lambda x: x["name"].lower())
    if args["--diff"]:
        diff(args["--diff"], imports)
        return
    if args["--clean"]:
        clean(args["--clean"], imports)
        return
    if args["--mode"]:
        scheme = args.get("--mode")
        if scheme in {"compat", "gt", "no-pin"}:
            imports, symbol = dynamic_versioning(scheme, imports)
        else:
            msg = "Invalid argument for mode flag, use 'compat', 'gt' or 'no-pin' instead"
            raise ValueError(msg)
    else:
        symbol = "=="
    if args["--print"]:
        output_requirements(imports, symbol)
        logging.info("Successfully output requirements")
    else:
        generate_requirements_file(path, imports, symbol)
        logging.info("Successfully saved requirements file in " + path)


def main() -> None:
    args = docopt(__doc__, version=__version__)
    log_level = logging.DEBUG if args["--debug"] else logging.INFO
    logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")
    try:
        init(args)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
