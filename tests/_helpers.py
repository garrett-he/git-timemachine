"""Test helper utilities."""

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
