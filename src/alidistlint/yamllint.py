"""Yamllint backend for alidistlint."""

import json
import re
from subprocess import run, PIPE, DEVNULL
import sys
from typing import Iterable

from alidistlint.common import Error, YAMLFilePart

LINE_PATTERN: re.Pattern = re.compile(r'''
^  (?P<fname>   .+?   )    :   # file name, be non-greedy
   (?P<line>    \d+   )    :   # line number
   (?P<column>  \d+   )    :\s # column number
\[ (?P<level>   \w+   ) \] \s  # error level (error or warning)
   (?P<message> .+    )    \s  # free-form message from yamllint
\( (?P<code>    [^)]+ ) \) $   # symbolic error code from yamllint
''', re.VERBOSE)


def yamllint(headers: dict[str, YAMLFilePart]) -> Iterable[Error]:
    """Run yamllint on a recipe's YAML header."""
    cmd = 'yamllint', '-f', 'parsable', '-d', json.dumps({
        # https://yamllint.readthedocs.io/en/stable/configuration.html
        'extends': 'default',
        'rules': {
            # Be more lenient on line length, e.g. for incremental_recipe.
            'line-length': {'max': 120, 'level': 'warning'},
            # Force 2-space indents. By default, yamllint only checks for
            # consistent indent width *within the file*, not across files.
            'indentation': {'spaces': 2, 'level': 'warning'},
            # Require no spaces before colons and one space after, but it's not
            # that critical.
            'colons': {'level': 'warning'},
            # YAML headers don't have a '---' line at the beginning.
            'document-start': 'disable',
            # Empty values are null, which we don't want.
            'empty-values': 'enable',
            # Don't allow {a: 1, b: 2}-style mappings (except {}).
            'braces': {'forbid': 'non-empty'},
            # Make bare 'on', 'off' and the like errors, not warnings.
            'truthy': {'level': 'error'},
            # YAML has a gotcha with automatic octal numbers.
            'octal-values': {
                # Numbers starting with 0 are octal. This is usually a mistake.
                'forbid-implicit-octal': True,
                # Numbers starting with 0o are OK.
                'forbid-explicit-octal': False,
            },
        },
    }), *headers.keys()
    try:
        result = run(cmd, stdout=PIPE, stderr=DEVNULL, text=True, check=False)
    except FileNotFoundError:
        print('yamllint is not installed; skipping', file=sys.stderr)
        return
    for line in result.stdout.splitlines():
        if not (match := re.search(LINE_PATTERN, line)):
            raise ValueError(f'could not parse yamllint output line {line!r}')
        part = headers[match['fname']]
        yield Error(
            match['level'],
            f"{match['message']} [yl:{match['code']}]",
            part.orig_file_name,
            int(match['line']) + part.line_offset,
            int(match['column']) + part.column_offset,
        )
