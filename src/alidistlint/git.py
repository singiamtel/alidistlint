"""Git integration for alidistlint.

This lets alidistlint check only added lines since a given revision, suitable
for incremental use in CI.
"""

from __future__ import annotations
from collections.abc import Iterable, Set
import itertools
import os

try:
    import pygit2
except ImportError:
    AVAILABLE = False
else:
    AVAILABLE = True


def find_repository(file_names: Iterable[str]) -> str | None:
    """Find a directory path pointing inside an alidist git repository.

    If input files are given, guess based on their names, falling back to the
    working directory. If no repository can be found, return None.
    """
    for name in itertools.chain((f for f in file_names if f != '<stdin>'),
                                (os.curdir,)):
        try:
            return pygit2.Repository(name).workdir
        except pygit2.GitError:
            continue
    return None


def added_lines(repo_path: str, revisions: str) -> Set[tuple[str, int]]:
    """Return (file, line) pairs specifying added lines between revisions."""
    assert AVAILABLE, 'pygit2 is not available; cannot read git repos'
    try:
        repo = pygit2.Repository(repo_path)
    except pygit2.GitError as exc:
        raise ValueError('invalid repository path', repo_path) from exc
    revs = repo.revparse(revisions)
    diff = repo.diff(revs.from_object, revs.to_object, context_lines=0)
    diff.find_similar()
    return {
        (patch.delta.new_file.path, hunk.new_start + rel_line)
        for patch in diff
        if patch.delta.similarity < 100
        for hunk in patch.hunks
        for rel_line in range(hunk.new_lines)
    }
