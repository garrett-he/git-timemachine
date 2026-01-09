"""A command-line tool that helps you record commits on Git repositories at any time node."""

from importlib.metadata import PackageNotFoundError, version

__version__: str

try:
    __version__ = version('git_timemachine')
except PackageNotFoundError:
    __version__ = 'unknown'
