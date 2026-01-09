"""Tests for git_timemachine version information."""

from importlib.metadata import PackageNotFoundError
from unittest.mock import patch

import git_timemachine


def test_version_is_string() -> None:
    """Verify that __version__ is defined and is a string."""
    assert hasattr(git_timemachine, '__version__')
    assert isinstance(git_timemachine.__version__, str)


def test_version_format() -> None:
    """Verify that __version__ follows semantic versioning format."""
    version: str = git_timemachine.__version__
    parts = version.split('.')
    assert len(parts) >= 2
    assert all(part.isdigit() for part in parts[:2])


def test_version_fallback_on_package_not_found() -> None:
    """Verify that __version__ falls back to 'unknown' when package metadata is missing."""
    import importlib

    with patch('importlib.metadata.version', side_effect=PackageNotFoundError):
        importlib.reload(git_timemachine)
    assert git_timemachine.__version__ == 'unknown'

    importlib.reload(git_timemachine)
