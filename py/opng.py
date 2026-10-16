from pathlib import Path

from dh import get_files, mpf3, runcmd


def process_file(file_path):
    try:
        runcmd(
            ["optipng", "-o7", str(file_path)],
            run_silently=False,
            show_output=True,
        )
        return True, file_path
    except:
        return False, file_path


def main() -> None:
    cwd = Path.cwd()
    files = get_files(cwd, extensions=[".png", ".PNG"])
    mpf3(process_file, files)


if __name__ == "__main__":
    main()
