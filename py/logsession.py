import subprocess
from datetime import datetime


def main() -> None:
    home = pathlib.Path("~").expanduser()
    log_dir = os.path.join(home, "tmp", "log")
    pathlib.Path(log_dir).mkdir(exist_ok=True, parents=True)
    log_path = os.path.join(
        log_dir,
        f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log",
    )
    shell = subprocess.Popen(
        os.environ.get("SHELL", "/bin/sh"),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )
    with pathlib.Path(log_path).open("w", encoding="utf-8") as log_file:
        while True:
            stdout_line = shell.stdout.readline()
            stderr_line = shell.stderr.readline()
            if not stdout_line and not stderr_line and shell.poll() is not None:
                break
            if stdout_line:
                log_file.write(stdout_line)
                log_file.flush()
            if stderr_line:
                log_file.write(stderr_line)
                log_file.flush()
    shell.wait()


if __name__ == "__main__":
    main()
