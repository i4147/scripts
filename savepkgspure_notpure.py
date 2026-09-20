import importlib.metadata
import multiprocessing as mp
from pathlib import Path
def check_package(dist):
    pkg_name = dist.name or dist.metadata.get("Name", "Unknown")
    files = dist.files or []
    has_c_ext = any(
        Path(file).suffix in (".so", ".pyd", ".c", ".cpp") for file in files
    )
    return pkg_name, not has_c_ext
def main():
    distributions = list(importlib.metadata.distributions())
    pure_pkgs = []
    not_pure_pkgs = []
    with mp.Pool(processes=8) as pool:
        async_results = [
            pool.apply_async(check_package, (dist,)) for dist in distributions
        ]
        for result in async_results:
            pkg_name, is_pure = result.get()
            if is_pure:
                pure_pkgs.append(pkg_name)
            else:
                not_pure_pkgs.append(pkg_name)
    pure_clean = sorted({p for p in pure_pkgs if p})
    not_pure_clean = sorted({p for p in not_pure_pkgs if p})
    pure_file = Path("pure.txt")
    pure_file.write_text("\n".join(pure_clean) + "\n", encoding="utf-8")
    not_pure_file = Path("notpure.txt")
    not_pure_file.write_text("\n".join(not_pure_clean) + "\n", encoding="utf-8")
    print(f"Done! Pure: {len(pure_clean)}, Not Pure: {len(not_pure_clean)}")
if __name__ == "__main__":
    main()
