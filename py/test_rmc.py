import argparse

import clean_code


def test_cli_options_exist() -> None:
    parser = argparse.ArgumentParser()
    clean_code.main.__globals__["argparse"] = argparse
    parser.add_argument("-f", "--file", help="Clean a single file")
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Recursively clean all .py files in current dir",
    )
    parser.add_argument(
        "--inplace",
        action="store_true",
        help="Update files in place",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=[".git", "dist", "venv", ".venv"],
        help="Directories to exclude",
    )
    opts = [a.option_strings for a in parser._actions]
    all_opts = [opt for group in opts for opt in group]
    assert "-f" in all_opts
    assert "--file" in all_opts
    assert "-r" in all_opts
    assert "--recursive" in all_opts
    assert "--inplace" in all_opts
    assert "--exclude" in all_opts
