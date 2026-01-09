"""Review command for displaying commit history by date."""

from datetime import datetime

import typer
from prettytable import PrettyTable
from pygit2 import Repository, discover_repository
from pygit2.errors import GitError


def review_command(ctx: typer.Context) -> None:
    """Review the commits of repository."""
    repo_dir = discover_repository(str(ctx.obj['repo_dir']))

    if repo_dir is None:
        raise GitError(f'"{repo_dir}" is not a git repository.')
        return

    repo = Repository(repo_dir)

    reports: dict[str, int] = {}
    if repo.is_empty:
        raise GitError(f'No commits in repository "{repo_dir}".')

    for commit in repo.walk(repo.head.target):
        date_str = datetime.fromtimestamp(commit.commit_time).strftime('%Y-%m-%d')

        if date_str in reports:
            reports[date_str] += 1
        else:
            reports[date_str] = 1

    table = PrettyTable()
    table.field_names = ['date', 'commits']

    for key, value in reports.items():
        table.add_row([key, value])

    typer.echo(table)
