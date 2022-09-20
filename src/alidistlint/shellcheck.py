'''Shellcheck backend for alidistlint.'''

import json
from subprocess import run, PIPE, DEVNULL
import sys
from typing import Iterable

from alidistlint.common import Error, FilePart


def shellcheck(recipes: Iterable[FilePart]) -> Iterable[Error]:
    '''Run shellcheck on a recipe.'''
    by_temp_name = {recipe.temp_file_name: recipe for recipe in recipes
                    if recipe.file_type == 'script'}
    # See shellcheck --list-optional.
    enabled_optional_checks = ','.join((
        # Suggest explicitly using -n in `[ $var ]`.
        'avoid-nullary-conditions',
        # Notify when set -e is suppressed during function invocation.
        'check-set-e-suppressed',
    ))
    cmd = 'shellcheck', '--format=json1', '--shell=bash', \
        '--enable', enabled_optional_checks, *by_temp_name.keys()
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
        recipe = by_temp_name[comment['file']]
        yield Error(
            comment['level'],
            f"{comment['message']} [SC{comment['code']}]",
            recipe.orig_file_name,
            comment['line'] + recipe.line_offset,
            comment['column'] + recipe.column_offset,
            comment['endLine'] + recipe.line_offset,
            comment['endColumn'] + recipe.column_offset,
        )
