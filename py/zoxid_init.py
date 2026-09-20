import builtins
import os
import os.path
import subprocess
import sys
import typing
import xonsh.dirstack  
import xonsh.environ  


def __zoxide_bin() -> str:
    zoxide = typing.cast(str, xonsh.environ.locate_binary("zoxide"))
    if zoxide is None:
        zoxide = "zoxide"
    return zoxide


def __zoxide_env() -> dict[str, str]:
    return builtins.__xonsh__.env.detype()  


def __zoxide_pwd() -> str:
    pwd = __zoxide_env().get("PWD")
    if pwd is None:
        raise RuntimeError("$PWD not found")
    pwd = os.getcwd()
    return pwd


def __zoxide_cd(path: str | bytes | None = None) -> None:
    if path is None:
        args = []
    elif isinstance(path, bytes):
        args = [path.decode("utf-8")]
    else:
        args = [path]
    _, exc, _ = xonsh.dirstack.cd(args)
    if exc is not None:
        raise RuntimeError(exc)
    print(__zoxide_pwd())


class ZoxideSilentException(Exception):
    pass


def __zoxide_errhandler(
    func: typing.Callable[[list[str]], None],
) -> typing.Callable[[list[str]], int]:

    def wrapper(args: list[str]) -> int:
        try:
            func(args)
            return 0
        except ZoxideSilentException:
            return 1
        except Exception as exc:
            print(f"zoxide: {exc}", file=sys.stderr)
            return 1

    return wrapper


if "__zoxide_hook" not in globals():

    @builtins.events.on_chdir  
    @builtins.events.on_post_prompt  
    def __zoxide_hook(**_kwargs: typing.Any) -> None:
        pwd = __zoxide_pwd()
        zoxide = __zoxide_bin()
        subprocess.run(
            [zoxide, "add", "--", pwd],
            check=False,
            env=__zoxide_env(),
        )


@__zoxide_errhandler
def __zoxide_z(args: list[str]) -> None:
    if args == []:
        __zoxide_cd()
    elif args == ["-"]:
        __zoxide_cd("-")
    elif len(args) == 1 and os.path.isdir(args[0]):
        __zoxide_cd(args[0])
    else:
        try:
            zoxide = __zoxide_bin()
            cmd = subprocess.run(
                [zoxide, "query", "--exclude", __zoxide_pwd(), "--"] + args,
                check=True,
                env=__zoxide_env(),
                stdout=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as exc:
            raise ZoxideSilentException() from exc
        result = cmd.stdout[:-1]
        __zoxide_cd(result)


@__zoxide_errhandler
def __zoxide_zi(args: list[str]) -> None:
    try:
        zoxide = __zoxide_bin()
        cmd = subprocess.run(
            [zoxide, "query", "-i", "--"] + args,
            check=True,
            env=__zoxide_env(),
            stdout=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        raise ZoxideSilentException() from exc
    result = cmd.stdout[:-1]
    __zoxide_cd(result)


builtins.aliases[""] = __zoxide_z  
builtins.aliases["i"] = __zoxide_zi  
