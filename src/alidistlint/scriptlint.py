'''Internal linter checking build recipe scripts for alidistlint.'''

from collections.abc import Iterable
import os.path
import re

from alidistlint.common import Error, ScriptFilePart


def scriptlint(scripts: dict[str, ScriptFilePart]) -> Iterable[Error]:
    '''Apply alidist-specific linting rules to build scripts.'''
    def make_error(message: str, code: str,
                   rel_line: int, rel_column: int,
                   level: str = 'error') -> Error:
        return Error(level, f'{message} [ali:{code}]',
                     script.orig_file_name,
                     rel_line + script.line_offset,
                     rel_column + script.column_offset)

    for script in scripts.values():
        modulefile_required = (
            not script.is_system_requirement and
            script.key_name is None and
            not os.path.basename(script.orig_file_name).startswith('defaults-')
        )
        if modulefile_required and \
           b'alibuild-generate-module' not in script.content and \
           b'#%Module' not in script.content:
            human_key_name = script.key_name or 'main recipe'
            yield make_error(
                f'{human_key_name} must create a Modulefile; use alibuild-'
                'generate-module or add a "#%Module1.0" comment to your '
                'manually-created Modulefile', 'missing-modulefile', 0, 0,
            )

        # At least the main script and the incremental_recipe should start with
        # the proper shebang. This lets shellcheck know that we use "bash -e"
        # to run scripts. For small recipes (like system_requirement_check),
        # this is probably more annoying than useful.
        if (script.key_name in (None, 'incremental_recipe') or
            # If the script already has a shebang, make sure it's correct.
            script.content.startswith(b'#!')) and \
           not script.content.startswith(b'#!/bin/bash -e\n'):
            yield make_error(
                'invalid or missing script shebang; use "#!/bin/bash -e" to '
                'match aliBuild script runner', 'bad-shebang', 0, 0, 'warning',
            )

        for lineno, line in enumerate(script.content.splitlines()):
            # Modules 4 does not allow having colons in prepend-path anymore
            prepend_path_pos = line.find(b'prepend-path')
            if prepend_path_pos != -1 and line.find(b':', prepend_path_pos) != -1:
                yield make_error(
                    'Modules 4 does not allow colons in prepend-path',
                    'colons-prepend-path', lineno, prepend_path_pos,
                )

            # This should really be cleaned up, since macOS cleans any
            # DYLD_LIBRARY_PATH when launching children processes, making it
            # completely irrelevant. aliBuild handles rpaths in macOS builds,
            # and any bugs should be fixed there.
            if re.search(br'(^\s*unset\s+)DYLD_LIBRARY_PATH\>', line):
                yield make_error('setting DYLD_LIBRARY_PATH is pointless',
                                 'dyld-library-path', lineno,
                                 line.find(b'DYLD_LIBRARY_PATH'), 'warning')

            # The following is a common (often copy-pasted) pattern in recipes:
            #   mkdir -p $INSTALLROOT/etc/modulefiles &&
            #   rsync -a --delete etc/modulefiles/ $INSTALLROOT/etc/modulefiles
            # However, the && just silently skips the rsync if the mkdir fails.
            if re.search(br'^[^#]*mkdir\s+.*etc/modulefiles\s*&&\s*'
                         br'rsync\s+.*etc/modulefiles', line):
                yield make_error(
                    '"mkdir && rsync" ignores errors if "mkdir" fails; '
                    'prefer writing the commands on separate lines',
                    'masked-exitcode', lineno, line.find(b'&&'), 'warning',
                )
