'''Internal linter checking build recipe scripts for alidistlint.'''

import os.path
from typing import Iterable

from alidistlint.common import Error, FilePart


def scriptlint(parts: Iterable[FilePart]) -> Iterable[Error]:
    '''Apply alidist-specific linting rules to build scripts.'''
    def make_error(message: str, code: str,
                   rel_line: int, rel_column: int) -> Error:
        return Error('error', f'{message} [ali:{code}]',
                     script.orig_file_name,
                     rel_line + script.line_offset,
                     rel_column + script.column_offset)

    yield Error('info', f'scriptlint started', '', 0, 0)

    for script in parts:
        yield Error('info', f'scriptlint got {script.temp_file_name}', '', 0, 0)
        if script.file_type != 'script':
            continue

        if not isinstance(script.content, str):
            yield make_error('script must be text, not '
                             f'{type(script.content).__name__}',
                             'invalid-type', 0, 0)
            continue

        modulefile_required = (
            not script.is_system_requirement and
            script.key_name is None and
            not os.path.basename(script.orig_file_name).startswith('defaults-')
        )
        if modulefile_required and \
           'alibuild-generate-module' not in script.content and \
           '#%Module' not in script.content:
            human_key_name = "main recipe" if script.key_name is None else script.key_name
            yield make_error(f'{human_key_name} should create a Modulefile',
                             'missing-modulefile', 0, 0)

        for lineno, line in enumerate(script.content.splitlines()):
            # Modules 4 does not allow having colons in prepend-path anymore
            prepend_path_pos = line.find('prepend-path')
            if prepend_path_pos != -1 and line.find(':', prepend_path_pos) != -1:
                yield make_error('Modules 4 does not allow colons in prepend-path',
                                 'colons-prepend-path', lineno, prepend_path_pos)

    yield Error('info', f'scriptlint finished', '', 0, 0)
