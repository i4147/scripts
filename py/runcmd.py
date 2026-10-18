def clean_response(raw: str) -> tuple[str, str]:
    text = ANSI_RE.sub("", raw).replace("\r\n", "\n").replace("\r", "\n")
    match = RECEIVED_RE.search(text)
    if match is not None:
        tail = text[match.end() :]
        tail = tail.split("\n", 1)[1] if "\n" in tail else ""
        text = LEADING_BLANK_RE.sub("", tail)
    text = AGENT_LINE_RE.sub("", text)
    text = FENCE_RE.sub("", text)
    text = SHELL_RE.sub("", text)
    text = PREAMBLE_RE.sub("", text.lstrip())
    text = LIVEDOC_RE.sub("", text).strip()
    if not text:
        return "", "empty after cleaning"
    if "\n" not in text:
        text = "\n".join(part.strip() for part in SENTENCE_RE.split(text) if part.strip())
    text = BLANK_RUN_RE.sub("\n\n", text)
    if STARTER_RE.match(text) is None:
        head = text[:300].lower()
        marker = next((item for item in REFUSAL_MARKERS if item in head), None)
        if marker is not None:
            return "", f"refusal marker {marker!r} in response head"
    return text, ""


def runcmd(
    cmd: Sequence[str],
    run_silently: bool = True,
    show_output: bool = True,
    timeout: float | None = None,
) -> tuple[int, str, str]:
    if not cmd or not cmd[0]:
        msg = "cmd must be a non-empty sequence of strings"
        raise ValueError(msg)

    if any(not isinstance(arg, str) for arg in cmd):
        msg = "All command arguments must be strings"
        raise TypeError(msg)

    command = list(cmd)

    def decode_output(data: bytes | str | None) -> str:
        if data is None:
            return ""

        if isinstance(data, str):
            return data

        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return clean_response(data.decode("utf-8", errors="replace"))

    def emit(stdout: str, stderr: str) -> None:
        if not show_output or run_silently:
            return

        if stdout:
            sys.stdout.write(stdout)
            sys.stdout.flush()

        if stderr:
            sys.stderr.write(stderr)
            sys.stderr.flush()

    def fail(code: int, message: str) -> tuple[int, str, str]:
        if show_output and not run_silently:
            print(message, file=sys.stderr)
        return code, "", message

    # Silent mode avoids buffering potentially large command output.
    stdout_target: int = subprocess.DEVNULL if run_silently else subprocess.PIPE
    stderr_target: int = subprocess.DEVNULL if run_silently else subprocess.PIPE

    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=stdout_target,
            stderr=stderr_target,
            timeout=timeout,
            check=False,
            text=False,
        )

        stdout = decode_output(result.stdout)
        stderr = decode_output(result.stderr)

        emit(stdout, stderr)
        return result.returncode, stdout, stderr

    except FileNotFoundError:
        return fail(127, f"Command not found: {command[0]!r}")

    except PermissionError:
        return fail(126, f"Permission denied: {command[0]!r}")

    except subprocess.TimeoutExpired as exc:
        stdout = decode_output(exc.stdout)
        stderr = decode_output(exc.stderr)

        message = f"Command timed out after {timeout}s: {' '.join(command)}"
        stderr = f"{stderr.rstrip()}\n{message}".lstrip()

        emit(stdout, stderr)
        return 124, stdout, stderr

    except OSError as exc:
        return fail(1, f"OS error running {command[0]!r}: {exc}")

    except Exception as exc:
        return fail(1, f"Unexpected error running {command[0]!r}: {exc}")


def runcmd(
    cmd: list[str], run_silently: bool = False, show_output: bool = True, timeout: float | None = None
) -> tuple[int, str, str]:
    from subprocess import DEVNULL as _DEVNULL
    from subprocess import TimeoutExpired as subprocess_TimeoutExpired
    from subprocess import run as subprocess_run
    from sys import stderr as sys_stderr
    from sys import stdout as sys_stdout

    if not cmd:
        raise ValueError("cmd must be a non-empty list (e.g., ['ls', '-l'])")
    try:
        if run_silently:
            result = subprocess_run(cmd, stdout=_DEVNULL, stderr=_DEVNULL, timeout=timeout)
            return (result.returncode, "", "")
        result = subprocess_run(cmd, capture_output=True, text=True, timeout=timeout)
        stdout, stderr = (result.stdout, result.stderr)
        if show_output:
            if stdout:
                sys_stdout.write(stdout)
                sys_stdout.flush()
            if stderr:
                sys_stderr.write(stderr)
                sys_stderr.flush()
        return (result.returncode, stdout, stderr)
    except FileNotFoundError:
        msg = f"Command not found: '{cmd[0]}'"
        if show_output and (not run_silently):
            print(msg, file=sys_stderr)
        return (127, "", msg)
    except PermissionError:
        msg = f"Permission denied: '{cmd[0]}'"
        if show_output and (not run_silently):
            print(msg, file=sys_stderr)
        return (126, "", msg)
    except subprocess_TimeoutExpired:
        msg = f"Command timed out after {timeout}s: {' '.join(cmd)}"
        if show_output and (not run_silently):
            print(msg, file=sys_stderr)
        return (124, "", msg)
    except Exception as e:
        msg = f"Unexpected error running '{cmd[0]}': {e}"
        if show_output and (not run_silently):
            print(msg, file=sys_stderr)
        return (1, "", msg)
