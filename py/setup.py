from distutils.extension import Extension
import glob
import os
import pathlib
import subprocess
import sys
from distutils.command.build import build

import setuptools
from pkg_resources import parse_version
from setuptools import find_packages, setup
from setuptools.command.install import install

base_dir = pathlib.Path(__file__).parent
src_dir = os.path.join(base_dir, "src")
sys.path.insert(0, src_dir)
use_system_lib = True
if os.environ.get("BUILD_LIB") == "1":
    use_system_lib = False


class CFFIBuild(build):
    def finalize_options(self) -> None:
        self.distribution.ext_modules = get_ext_modules()
        build.finalize_options(self)


class CFFIInstall(install):
    def finalize_options(self) -> None:
        self.distribution.ext_modules = get_ext_modules()
        install.finalize_options(self)


def build_ssdeep() -> None:
    returncode = subprocess.call(
        "(cd src/ssdeep-lib && sh configure && make)",
        shell=True,
    )
    if returncode == 0:
        return
    print("Failed while building ssdeep lib with configure and make.")
    print("Retry with autoreconf ...")
    returncode = subprocess.call(
        "(cd src/ssdeep-lib && libtoolize && autoreconf --force)",
        shell=True,
    )
    if returncode != 0:
        returncode = subprocess.call(
            "(cd src/ssdeep-lib && automake --add-missing && autoreconf --force)",
            shell=True,
        )
        if returncode != 0:
            sys.exit("Failed to reconfigure the project build.")
    returncode = subprocess.call(
        "(cd src/ssdeep-lib && sh configure && make)",
        shell=True,
    )
    if returncode != 0:
        sys.exit("Failed while building ssdeep lib.")


def get_ext_modules() -> list[Extension]:
    from ssdeep.binding import Binding

    if use_system_lib:
        binding = Binding()
    else:
        build_ssdeep()
        binding = Binding(
            extra_objects=get_objects(),
            include_dirs=["./src/ssdeep-lib/"],
            libraries=[],
        )
    binding.verify()
    return [binding.ffi.verifier.get_extension()]


def get_objects() -> list[str]:
    objects = glob.glob("src/ssdeep-lib/.libs/*.o")
    if len(objects) > 0:
        return objects
    return glob.glob("src/ssdeep-lib/.libs/*.obj")


about = {}
with pathlib.Path(os.path.join(src_dir, "ssdeep", "__about__.py")).open(encoding="utf-8") as f:
    exec(f.read(), about)
long_description = pathlib.Path(os.path.join(base_dir, "README.rst")).read_text(encoding="utf-8")
if parse_version(setuptools.__version__) < parse_version("12"):
    setup_requires = ["pytest-runner<2.4"]
else:
    setup_requires = ["pytest-runner"]
setup(
    name=about["__title__"],
    version=about["__version__"],
    description=about["__summary__"],
    long_description=long_description,
    license=about["__license__"],
    url=about["__uri__"],
    zip_safe=False,
    author=about["__author__"],
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: GNU Lesser General Public License v3 or later (LGPLv3+)",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.2",
        "Programming Language :: Python :: 3.3",
        "Programming Language :: Python :: 3.4",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python :: Implementation :: PyPy",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    keywords="ssdeep",
    package_dir={"": "src"},
    packages=find_packages(
        where="src",
        exclude=["_cffi_src", "_cffi_src.*"],
    ),
    include_package_data=True,
    cmdclass={
        "build": CFFIBuild,
        "install": CFFIInstall,
    },
    ext_package="ssdeep",
)
