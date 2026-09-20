from _frozen_importlib import ModuleSpec
import importlib.abc
import importlib.machinery
import os
import pathlib
import sys
import zipimport


class ZipPackageLoader(
    importlib.abc.Loader,
    importlib.abc.ResourceLoader,
):
    def __init__(
        self,
        zpath: str = "/data/data/vom.termux/files/usr/lib/python3.12",
    ) -> None:
        self.zip_dir = os.path.join(zpath, "zipped-pkgs")
        self.path = zpath
        self.loaded_packages = {}

    def find_spec(self, fullname, path, target=None) -> ModuleSpec | None:
        pkg_name = fullname.split(".")[0]
        zip_path = os.path.join(self.zip_dir, f"{pkg_name}.zip")
        if pathlib.Path(zip_path).exists():
            return importlib.machinery.ModuleSpec(
                fullname,
                self,
                is_package=True,
                origin=zip_path,
            )
        return None

    def create_module(self, spec) -> None:
        return None

    def exec_module(self, module) -> None:
        zip_path = spec.origin
        importer = zipimport.zipimporter(zip_path)
        try:
            if spec.name in importer._files:
                code = importer.get_code(spec.name)
                exec(code, module.__dict__)
            else:
                pkg_path = spec.name.replace(".", "/")
                code = importer.get_code(f"{pkg_path}/__init__")
                exec(code, module.__dict__)
                module.__path__ = [f"{zip_path}/{pkg_path}"]
        except Exception:
            module = importer.load_module(spec.name)
            sys.modules[spec.name] = module
