"""Shellcheck backend for alidistlint."""

import json
from subprocess import run, PIPE, DEVNULL
import sys
from typing import Iterable

from alidistlint.common import Error, FileParts


def shellcheck(recipes: FileParts) -> Iterable[Error]:
    """Run shellcheck on a recipe."""
    # See shellcheck --list-optional.
    enabled_optional_checks = ','.join((
        # Suggest explicitly using -n in `[ $var ]`.
        'avoid-nullary-conditions',
        # Notify when set -e is suppressed during function invocation.
        'check-set-e-suppressed',
    ))
    cmd = 'shellcheck', '--format=json1', '--shell=bash', \
        '--enable', enabled_optional_checks, *recipes.keys()
    try:
        result = run(cmd, stdout=PIPE, stderr=DEVNULL, text=True, check=False)
    except FileNotFoundError:
        # shellcheck is not installed
        print('shellcheck is not installed; skipping', file=sys.stderr)
        return
    try:
        comments = json.loads(result.stdout)['comments']
    except (json.JSONDecodeError, KeyError) as exc:
        raise ValueError('failed to parse shellcheck output') from exc
    for comment in comments:
        orig_file_name, line_offset, column_offset, _ = \
            recipes[comment['file']]
        yield Error(
            comment['level'],
            f"{comment['message']} [SC{comment['code']}]",
            orig_file_name,
            comment['line'] + line_offset,
            comment['column'] + column_offset,
            comment['endLine'] + line_offset,
            comment['endColumn'] + column_offset,
        )
