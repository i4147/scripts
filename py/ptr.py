import contextlib as _contextlib
import itertools as _itertools
import operator as _operator
import os as _os
import shlex as _shlex
import sys as _sys
import warnings as _warnings

import pkg_resources
import setuptools.command.test as orig
from setuptools import Distribution


@_contextlib.contextmanager
def _save_argv(repl: list[str] | None = None):
    saved = _sys.argv[:]
    if repl is not None:
        _sys.argv[:] = repl
    try:
        yield saved
    finally:
        _sys.argv[:] = saved


class CustomizedDist(Distribution):
    allow_hosts = None
    index_url = None

    def fetch_build_egg(self, req):
        from setuptools.command.easy_install import easy_install

        dist = Distribution({"script_args": ["easy_install"]})
        dist.parse_config_files()
        opts = dist.get_option_dict("easy_install")
        keep = (
            "find_links",
            "site_dirs",
            "index_url",
            "optimize",
            "site_dirs",
            "allow_hosts",
        )
        for key in list(opts):
            if key not in keep:
                del opts[key]
        if self.dependency_links:
            links = self.dependency_links[:]
            if "find_links" in opts:
                links = opts["find_links"][1].split() + links
            opts["find_links"] = ("setup", links)
        if self.allow_hosts:
            opts["allow_hosts"] = ("test", self.allow_hosts)
        if self.index_url:
            opts["index_url"] = ("test", self.index_url)
        install_dir_func = getattr(self, "get_egg_cache_dir", _os.getcwd)
        install_dir = install_dir_func()
        cmd = easy_install(
            dist,
            args=["x"],
            install_dir=install_dir,
            exclude_scripts=True,
            always_copy=False,
            build_directory=None,
            editable=False,
            upgrade=False,
            multi_version=True,
            no_report=True,
            user=False,
        )
        cmd.ensure_finalized()
        return cmd.easy_install(req)


class PyTest(orig.test):
    user_options = [
        ("extras", None, "Install (all) setuptools extras when running tests"),
        (
            "index-url=",
            None,
            "Specify an index url from which to retrieve dependencies",
        ),
        (
            "allow-hosts=",
            None,
            "Whitelist of comma-separated hosts to allow when retrieving dependencies",
        ),
        (
            "addopts=",
            None,
            "Additional options to be passed verbatim to the pytest runner",
        ),
    ]

    def initialize_options(self) -> None:
        self.extras = False
        self.index_url = None
        self.allow_hosts = None
        self.addopts = []
        self.ensure_setuptools_version()

    @staticmethod
    def ensure_setuptools_version() -> None:
        pkg_resources.require("setuptools>=27.3")

    def finalize_options(self) -> None:
        if self.addopts:
            self.addopts = _shlex.split(self.addopts)

    @staticmethod
    def marker_passes(marker):
        return not marker or (not pkg_resources.invalid_marker(marker) and pkg_resources.evaluate_marker(marker))

    def install_dists(self, dist: CustomizedDist):
        return _itertools.chain(orig.test.install_dists(dist), self.install_extra_dists(dist))

    def install_extra_dists(self, dist):
        extras_require = dist.extras_require or {}
        spec_extras = ((spec.partition(":"), reqs) for spec, reqs in extras_require.items())
        matching_extras = (
            reqs
            for (name, sep, marker), reqs in spec_extras
            if (not name or self.extras) and self.marker_passes(marker)
        )
        results = list(map(dist.fetch_build_eggs, matching_extras))
        return _itertools.chain.from_iterable(results)

    @staticmethod
    def _warn_old_setuptools() -> None:
        msg = (
            "pytest-runner will stop working on this version of setuptools; "
            "please upgrade to setuptools 30.4 or later or pin to "
            "pytest-runner < 5."
        )
        ver_str = pkg_resources.get_distribution("setuptools").version
        ver = pkg_resources.parse_version(ver_str)
        if ver < pkg_resources.parse_version("30.4"):
            _warnings.warn(msg, stacklevel=2)

    def run(self) -> None:
        self._warn_old_setuptools()
        dist = CustomizedDist()
        for attr in ["allow_hosts", "index_url"]:
            setattr(dist, attr, getattr(self, attr))
        for attr in [
            "dependency_links",
            "install_requires",
            "tests_require",
            "extras_require",
        ]:
            setattr(dist, attr, getattr(self.distribution, attr))
        installed_dists = self.install_dists(dist)
        if self.dry_run:
            self.announce("skipping tests (dry run)")
            return None
        paths = map(_operator.attrgetter("location"), installed_dists)
        with self.paths_on_pythonpath(paths), self.project_on_sys_path():
            return self.run_tests()

    @property
    def _argv(self):
        return ["pytest", *self.addopts]

    def run_tests(self) -> None:
        with _save_argv(_sys.argv[:1] + self.addopts):
            result_code = __import__("pytest").main()
            if result_code:
                raise SystemExit(result_code)
