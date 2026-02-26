"""Settings and state models for git-timemachine."""

from datetime import date, datetime
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, Field

T = TypeVar('T', bound='BaseConfig')


class BaseConfig(BaseModel):
    """Base configuration with YAML load/save support."""

    _path: Path = Path()

    @classmethod
    def load(cls: type[T], path: Path) -> T:
        """Load configuration from a YAML file."""
        with path.open('r', encoding='utf-8') as f:
            config = cls.model_validate(yaml.safe_load(f))
            config._path = path

            return config

    def save(self, path: Path | None = None) -> None:
        """Save configuration to a YAML file."""
        if path is None:
            path = self._path

        path.write_text(yaml.dump(self.model_dump(), sort_keys=False), encoding='utf-8')

    def save_atomic(self, path: Path | None = None) -> None:
        """Save configuration to a YAML file through a temporary file."""
        if path is None:
            path = self._path

        temp_path = path.with_name(f'{path.name}.tmp')
        temp_path.write_text(yaml.dump(self.model_dump(), sort_keys=False), encoding='utf-8')
        temp_path.replace(path)


class Settings(BaseConfig):
    """Application settings."""

    max_repo_daily_commits: int = Field(default=5, gt=0)
    max_total_daily_commits: int = Field(default=15, gt=0)
    jitter_min: int = Field(default=600, gt=0)
    jitter_max: int = Field(default=3600, gt=0)


class States(BaseConfig):
    """Persistent state tracking last commit time and update checks."""

    last_commit_time: datetime = Field(default_factory=datetime.now)
    current_commit_date: date = Field(default_factory=date.today)
    daily_commit_count: int = Field(default=0, ge=0)


class RetimeCommit(BaseModel):
    """Snapshot of a commit scheduled for a retime replay."""

    oid: str
    is_empty: bool


class RetimeSession(BaseConfig):
    """Persisted progress of an interrupted retime session."""

    version: int = 1
    original_head: str
    branch: str
    backup_branch: str
    parent_oid: str | None = None
    commits: list[RetimeCommit]
    next_index: int = Field(default=0, ge=0)
    last_new_head: str | None = None
    reset_done: bool = False
