import argparse
import sys
from pathlib import Path
from .core import Downloader, PackageNotFound
from .resolver import DependencyResolver


def main():
    parser = argparse.ArgumentParser(description="Download Python packages from PyPI", prog="pyget")
    parser.add_argument("package", help="Package name")
    parser.add_argument("-v", "--version", help="Specific version")
    parser.add_argument("-o", "--output", default=".", help="Output directory")
    parser.add_argument("--source", action="store_true", help="Prefer source distributions")
    parser.add_argument("-d", "--deps", action="store_true", help="Resolve dependencies")
    parser.add_argument("-w", "--workers", type=int, default=4, help="Parallel workers")
    parser.add_argument("-t", "--timeout", type=int, default=10, help="Request timeout (s)")

    args = parser.parse_args()

    try:
        downloader = Downloader(output_dir=args.output, timeout=args.timeout, max_workers=args.workers)

        if args.deps:
            resolver = DependencyResolver(downloader)
            packages = resolver.resolve(args.package, args.version)
            print(f"Resolved {len(packages)} packages: {', '.join(sorted(packages))}")
        else:
            packages = [args.package]

        all_files = []
        for pkg in packages:
            files = downloader.download(pkg, version=args.version, prefer_wheels=not args.source, parallel=True)
            all_files.extend(files)
            print(f"Downloaded {pkg}: {len(files)} file(s)")

        print(f"\nTotal: {len(all_files)} file(s) → {Path(args.output).resolve()}")

    except PackageNotFound as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
