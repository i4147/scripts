import sys
import traceback
from importlib import import_module
from importlib.metadata import distributions
from loguru import logger

logger.add("/sdcard/allimport.log", diagnose=True)


def tryimport(package):
    try:
        import_module(package)
        print(f"✓ {package}")
        return True
    except Exception:
        logger.debug(f"X {package}")
        return traceback.format_exc()


def tryallimport():
    for pkg in distributions():
        pkn = pkg.metadata["name"]
        try:
            import_module(pkn)
            print(f"✓ {pkn}")
        except Exception:
            logger.debug(f"X {pkn}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args:
        pkgs = list(args)
        for pkg in pkgs:
            tryimport(pkg)
    else:
        tryallimport()
    sys.exit(0)
