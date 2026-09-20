import distutils.command.build_scripts
import io
import os
import platform
import sys
from distutils import log
from distutils.dep_util import newer
from distutils.util import convert_path
from distutils.util import get_platform
import setuptools.command.install
from skbuild import setup

try:
    from wheel.bdist_wheel import bdist_wheel

    class CustomBDistWheel(bdist_wheel):
        def finalize_options(self):
            bdist_wheel.finalize_options(self)
            self.root_is_pure = False

        def get_tag(self):
            return ("py3", "none") + bdist_wheel.get_tag(self)[2:]
except ImportError:
    print("afdko: setup.py requires that the Python package 'wheel' be installed. Try the command 'pip install wheel'.")
    sys.exit(1)


class InstallPlatlib(setuptools.command.install.install):
    def finalize_options(self):
        setuptools.command.install.install.finalize_options(self)
        self.install_lib = self.install_platlib


class CustomBuildScripts(distutils.command.build_scripts.build_scripts):
    def copy_scripts(self):
        self.mkpath(self.build_dir)
        outfiles = []
        updated_files = []
        for script in self.scripts:
            script = convert_path(script)
            outfile = os.path.join(self.build_dir, os.path.basename(script))
            outfiles.append(outfile)
            if not self.force and (not newer(script, outfile)):
                log.debug("afdko: not copying %s (up-to-date)", script)
                continue
            try:
                f = open(script, "rb")
            except OSError:
                if not self.dry_run:
                    raise
                f = None
            else:
                first_line = f.readline()
                if not first_line:
                    f.close()
                    self.warn("afdko: %s is an empty file (skipping)" % script)
                    continue
            if f:
                f.close()
            updated_files.append(outfile)
            self.copy_file(script, outfile)
        return (outfiles, updated_files)


def _get_scripts():
    script_names = ["detype1", "makeotfexe", "mergefonts", "rotatefont", "sfntdiff", "sfntedit", "spot", "tx", "type1"]
    if platform.system() == "Windows":
        extension = ".exe"
    else:
        extension = ""
    scripts = [f"bin/{script_name}{extension}" for script_name in script_names]
    return scripts


def _get_console_scripts():
    script_entries = [
        ("buildcff2vf", "buildcff2vf:main"),
        ("buildmasterotfs", "buildmasterotfs:main"),
        ("comparefamily", "comparefamily:main"),
        ("checkoutlinesufo", "checkoutlinesufo:main"),
        ("makeotf", "makeotf:main"),
        ("makeinstancesufo", "makeinstancesufo:main"),
        ("otc2otf", "otc2otf:main"),
        ("otf2otc", "otf2otc:main"),
        ("otf2ttf", "otf2ttf:main"),
        ("ttfcomponentizer", "ttfcomponentizer:main"),
        ("ttfdecomponentizer", "ttfdecomponentizer:main"),
        ("ttxn", "ttxn:main"),
        ("charplot", "proofpdf:charplot"),
        ("digiplot", "proofpdf:digiplot"),
        ("fontplot", "proofpdf:fontplot"),
        ("fontplot2", "proofpdf:fontplot2"),
        ("fontsetplot", "proofpdf:fontsetplot"),
        ("hintplot", "proofpdf:hintplot"),
        ("waterfallplot", "proofpdf:waterfallplot"),
        ("otfautohint", "otfautohint.__main__:main"),
        ("otfstemhist", "otfautohint.__main__:stemhist"),
    ]
    scripts_path = "afdko"
    scripts = [f"{name} = {scripts_path}.{entry}" for name, entry in script_entries]
    return scripts


def _get_requirements():
    with io.open("requirements.txt", encoding="utf-8") as requirements:
        return [rl.replace("==", ">=") for rl in requirements.readlines()]


def main():
    classifiers = [
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Build Tools",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3.9",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: POSIX :: Linux",
    ]
    with io.open("README.md", encoding="utf-8") as readme:
        long_description = readme.read()
    long_description += "\n"
    platform_name = get_platform()
    setup(
        name="afdko",
        use_scm_version=True,
        description="Adobe Font Development Kit for OpenType",
        long_description=long_description,
        long_description_content_type="text/markdown",
        url="https://github.com/adobe-type-tools/afdko",
        author="Adobe Type team & friends",
        author_email="afdko@adobe.com",
        license="Apache License, Version 2.0",
        classifiers=classifiers,
        keywords="font development tools",
        platforms=[platform_name],
        package_dir={"": "python"},
        packages=["afdko", "afdko.pdflib", "afdko.otfautohint"],
        include_package_data=True,
        package_data={
            "afdko": [
                "resources/*.txt",
                "resources/Adobe-CNS1/*",
                "resources/Adobe-GB1/*",
                "resources/Adobe-Japan1/*",
                "resources/Adobe-Korea1/*",
            ]
        },
        zip_safe=False,
        python_requires=">=3.9",
        setup_requires=["wheel", "setuptools_scm", "scikit-build", "cmake", "ninja"],
        tests_require=["pytest"],
        install_requires=_get_requirements(),
        scripts=_get_scripts(),
        entry_points={"console_scripts": _get_console_scripts()},
        cmdclass={"build_scripts": CustomBuildScripts, "bdist_wheel": CustomBDistWheel, "install": InstallPlatlib},
    )


if __name__ == "__main__":
    main()
