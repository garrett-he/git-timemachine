"""Test helper utilities."""

import os
import subprocess
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from chance import chance  # type: ignore[import-untyped]
from pygit2 import Repository


def repo_add_new_file(repo: Repository) -> Path:
    """Add a new random file to the repository index."""
    path = Path(repo.workdir, chance.word())
    path.write_text(chance.sentence(), encoding='utf-8')

    repo.index.add_all()
    repo.index.write()

    return path


def run_git(path: Path, *args: str, env: Mapping[str, str] | None = None) -> str:
    """Run a git command inside the given repository path and return stdout."""
    result = subprocess.run(
        ['git', '-C', str(path), *args],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )

    return result.stdout


def init_repo(path: Path) -> Repository:
    """Initialize a repository with a deterministic identity on branch main."""
    path.mkdir(parents=True, exist_ok=True)
    run_git(path, 'init', '-q', '-b', 'main')
    run_git(path, 'config', 'user.name', 'Test User')
    run_git(path, 'config', 'user.email', 'test@example.com')

    return Repository(str(path))


def commit_files(
    path: Path,
    files: Mapping[str, bytes],
    message: str,
    when: datetime,
    *,
    author: str | None = None,
    allow_empty: bool = False,
) -> str:
    """Create a commit containing the given files and return its SHA."""
    for name, content in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    run_git(path, 'add', '--all')

    args = ['commit', '-q', '-m', message]
    if author is not None:
        args.append(f'--author={author}')
    if allow_empty:
        args.append('--allow-empty')

    date = when.astimezone().isoformat()
    run_git(path, *args, env={'GIT_AUTHOR_DATE': date, 'GIT_COMMITTER_DATE': date})

    return run_git(path, 'rev-parse', 'HEAD').strip()


def install_failing_hook(path: Path, name: str = 'pre-commit') -> None:
    """Install a hook that always fails."""
    hook = path / '.git' / 'hooks' / name
    hook.write_text('#!/bin/sh\nexit 1\n', encoding='utf-8')
    hook.chmod(0o755)
