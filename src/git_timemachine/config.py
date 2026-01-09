"""Settings and state models for git-timemachine."""

from datetime import datetime
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


class Settings(BaseConfig):
    """Application settings."""

    max_repo_daily_commits: int = Field(default=5, gt=0)
    jitter_min: int = Field(default=600, gt=0)
    jitter_max: int = Field(default=3600, gt=0)


class States(BaseConfig):
    """Persistent state tracking last commit time and update checks."""

    last_commit_time: datetime = Field(default_factory=datetime.now)
