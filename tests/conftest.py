"""Shared fixtures for git-timemachine tests."""

import os
import shutil
import tarfile
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from chance import chance
from pygit2 import Repository, discover_repository
from typer.testing import CliRunner

from git_timemachine.config import Settings, States


def copy_asset(filename: str, path: Path) -> Path:
    """Copy a test asset file to the given directory."""
    dest_path = path / filename
    shutil.copy(Path(__file__).with_suffix('').parent / 'assets' / filename, dest_path)

    return dest_path


@pytest.fixture(scope='function')
def temp_dir() -> Generator[Path, None, None]:
    """Provide a temporary directory that is cleaned up after the test."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def extract_repo(filename: str, target: str) -> None:
    """Extract a repository tarball into the target directory."""
    with tarfile.open(Path(__file__).parent.joinpath('assets', filename)) as tar:
        tar.extractall(target, filter='data')


@pytest.fixture(scope='function')
def empty_repo() -> Generator[Repository, None, None]:
    """Provide an empty git repository for testing."""
    with tempfile.TemporaryDirectory() as td:
        extract_repo('empty-repo.tar.gz', td)
        yield Repository(discover_repository(td))


@pytest.fixture(scope='function')
def nonempty_repo() -> Generator[Repository, None, None]:
    """Provide a non-empty git repository for testing."""
    with tempfile.TemporaryDirectory() as td:
        extract_repo('nonempty-repo.tar.gz', td)
        yield Repository(discover_repository(td))


@pytest.fixture(scope='module')
def runner() -> CliRunner:
    """Provide a Typer CLI test runner."""
    return CliRunner()


@pytest.fixture(autouse=True)
def gitconfig(tmp_path: Path) -> Generator[None, None, None]:
    """Disable GPG signing via a temporary git config for all tests."""
    config_file = tmp_path / 'gitconfig'
    config_file.write_text('[commit]\n    gpgSign = false\n', encoding='utf-8')

    old_value = os.environ.get('GIT_CONFIG_GLOBAL')
    os.environ['GIT_CONFIG_GLOBAL'] = str(config_file)

    yield

    if old_value is None:
        os.environ.pop('GIT_CONFIG_GLOBAL', None)
    else:
        os.environ['GIT_CONFIG_GLOBAL'] = old_value


@pytest.fixture(scope='function')
def gtm_settings() -> Generator[Settings, None, None]:
    """Provide a temporary settings file and set env vars."""
    with tempfile.NamedTemporaryFile(mode='w+', delete=False) as file:
        max_repo_daily_commits = 5
        jitter_min = 600
        jitter_max = 3600

        file.write(
            f'max_repo_daily_commits: {max_repo_daily_commits}\njitter_min: {jitter_min}\njitter_max: {jitter_max}\n'
        )
        file.flush()

        os.environ['GIT_TIMEMACHINE_SETTINGS'] = file.name

        yield Settings.load(Path(file.name))

        file.close()
        os.unlink(file.name)


@pytest.fixture(scope='function')
def gtm_states() -> Generator[States, None, None]:
    """Provide a temporary states file and set env vars."""
    with tempfile.NamedTemporaryFile(mode='w+', delete=False) as file:
        last_commit_time = chance.date(2023, 1, 1).astimezone().strftime('%Y-%m-%dT%H:%M:%S')

        file.write(f'last_commit_time: {last_commit_time}')
        file.flush()

        os.environ['GIT_TIMEMACHINE_STATES'] = file.name

        yield States.load(Path(file.name))

        file.close()
        os.unlink(file.name)
