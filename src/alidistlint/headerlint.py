'''Internal linter checking YAML headers for alidistlint.'''

import re
import os.path
from typing import Any, Iterable

import cerberus
import yaml

from alidistlint.common import Error, FileParts, position_of_key, TrackedLocationLoader

ValidationErrors = list[str | dict[Any, 'ValidationErrors']]
ValidationErrorTree = str | dict[Any, ValidationErrors] | ValidationErrors
'''An error tree as produced by cerberus.'''

ObjectPath = tuple[str | int, ...]
'''Specifies where in a nested object a value is located as a series of keys.

For instance, A is at path (0, "a") in the object [{"a": A}].
'''


def get_schema_for_file(file_name: str) -> dict:
    '''Construct a schema to validate the YAML header of the given file.'''
    def package_name_matches(field, value, error):
        basename = os.path.basename(file_name)
        if f'{value.lower()}.sh' != basename:
            error(field, f'must match the file name {basename!r} '
                  'case-insensitively, excluding the .sh')

    def is_valid_require(field, value, error):
        _, sep, arch_re = value.partition(':')
        if sep:
            try:
                re.compile(arch_re)
            except re.error as exc:
                error(field, f'invalid architecture regex after colon: {exc}')

    def environment_schema(allow_list_values=False):
        return {
            'type': 'dict',
            'keysrules': {
                'type': 'string',
                'regex': r'^[a-zA-Z_][a-zA-Z0-9_]+$',
            },
            'valuesrules': {
                'anyof': [
                    {'type': 'string'},
                    {'type': 'list', 'schema': {'type': 'string'}},
                ],
            } if allow_list_values else {'type': 'string'},
        }

    def version_string_ok(field, value, error):
        if not file_name.startswith('defaults-') and \
           '%(defaults_upper)s' in value:
            error(field, 'cannot use %(defaults_upper)s in non-default recipe')

    def is_valid_regex(field, value, error):
        try:
            re.compile(value)
        except re.error as exc:
            error(field, f'invalid regex: {exc}')

    def is_relative_toplevel_path(field, value, error):
        if value.startswith('/'):
            error(field, 'expecting a relative path')
        if '/' in value:
            error(field, 'expecting a toplevel path (i.e. without slashes)')

    requires = {
        'type': 'list',
        'schema': {
            'type': 'string',
            'check_with': is_valid_require,
        }
    }

    git_url = {
        'type': 'string',
        'regex': r'^(https?|git)://.*$',
    }

    environment = environment_schema(allow_list_values=False)
    path_environment = environment_schema(allow_list_values=True)

    # This contains most keys, and can be used in other packages' override:.
    override_package = {
        'version': {'type': 'string', 'check_with': version_string_ok},
        'tag': {'type': 'string'},
        'source': git_url,
        'write_repo': git_url,
        'requires': requires,
        'build_requires': requires,
        'env': environment,
        'valid_defaults': {'type': 'list', 'schema': {'type': 'string'}},
        'prepend_path': path_environment,
        'append_path': path_environment,
        'force_rebuild': {'type': 'boolean'},
        'incremental_recipe': {'type': 'string'},
        'prefer_system': {'type': 'string', 'check_with': is_valid_regex},
        'prefer_system_check': {'type': 'string'},
        'system_requirement': {
            'type': 'string',
            'check_with': is_valid_regex,
            'dependencies': ('system_requirement_check',),
        },
        'system_requirement_check': {
            'type': 'string',
            'dependencies': ('system_requirement',),
        },
        'system_requirement_missing': {
            'type': 'string',
            'dependencies': ('system_requirement',),
        },
        'relocate_paths': {
            'type': 'list',
            'schema': {
                'type': 'string',
                'check_with': is_relative_toplevel_path,
            },
        },
    }

    return {
        'package': {
            'required': True,
            'type': 'string',
            'check_with': package_name_matches,
        },
        **override_package,
        # At the top level, the version key is required.
        'version': {
            'required': True,
            'type': 'string',
            'check_with': version_string_ok,
        },
        'disable': {'type': 'list', 'schema': {'type': 'string'}},
        'overrides': {
            'type': 'dict',
            'keysrules': {'type': 'string'},
            'valuesrules': {'type': 'dict', 'schema': override_package},
        },
    }


def emit_validation_errors(error_tree: ValidationErrorTree,
                           tagged_validated_object: dict,
                           file_name: str,
                           line_offset: int, column_offset: int,
                           path: ObjectPath = ()) -> Iterable[Error]:
    '''Parse any validation errors from a cerberus validator.'''
    if isinstance(error_tree, dict):
        for key, suberrors in error_tree.items():
            yield from emit_validation_errors(
                suberrors, tagged_validated_object, file_name,
                line_offset, column_offset, path + (key,),
            )
    elif isinstance(error_tree, list):
        for subtree in error_tree:
            yield from emit_validation_errors(
                subtree, tagged_validated_object, file_name,
                line_offset, column_offset, path,
            )
    elif isinstance(error_tree, str):
        line, column = position_of_key(tagged_validated_object, path)
        dotted_subpath = '.'.join(map(str, path))
        yield Error('error', f'{dotted_subpath}: {error_tree} [ali:schema]',
                    file_name, line + line_offset, column + column_offset)
    else:
        raise TypeError(f'cannot handle {error_tree!r}')


def check_keys_order(data: dict[str, Any], orig_file_name: str,
                     line_offset: int, column_offset: int) -> Iterable[Error]:
    '''Produce errors relating to key order in the YAML header data.'''
    def make_error(message: str, key: str) -> Error:
        rel_line, rel_column = position_of_key(data, (key,))
        return Error('error', f'{message} [ali:key-order]', orig_file_name,
                     rel_line + line_offset, rel_column + column_offset)

    keys = list(data.keys())
    if 'requires' in data and 'build_requires' in data and \
       keys.index('requires') > keys.index('build_requires'):
        for key in ('requires', 'build_requires'):
            yield make_error('requires must come before build_requires', key)
    if 'package' in data:
        if keys.index('package') != 0:
            yield make_error('package: must be the first key in the file',
                             'package')
        if 'version' in data and keys.index('version') != 1:
            yield make_error('version: must be the second key in the file '
                             '(after package)', 'version')
        if 'tag' in data and keys.index('tag') != 2:
            yield make_error('tag: must be the third key in the file '
                             '(after version)', 'tag')
    else:
        if 'version' in data and keys.index('version') != 0:
            yield make_error('version: must be the first key in the override '
                             'declaration', 'version')
        if 'tag' in data and keys.index('tag') != 1:
            yield make_error('tag: must be the second key in the override '
                             'declaration (after version)', 'tag')


def headerlint(headers: FileParts) -> Iterable[Error]:
    '''Apply alidist-specific linting rules to YAML headers.'''
    def make_error(message: str, code: str,
                   rel_line: int, rel_column: int) -> Error:
        return Error('error', f'{message} [ali:{code}]', orig_file_name,
                     rel_line + line_offset, rel_column + column_offset)

    for header in headers.values():  # we don't need the temporary file
        orig_file_name, line_offset, column_offset, yaml_text = header
        if not yaml_text:
            yield make_error('metadata not found or empty '
                             "(is the '\\n---\\n' separator present?)",
                             'empty', 1, 0)
            return

        # Parse the source YAML, keeping track of the locations of keys.
        try:
            tagged_data = yaml.load(yaml_text, TrackedLocationLoader)
        except yaml.MarkedYAMLError as exc:
            mark = exc.problem_mark
            yield make_error(f'parse error: {exc.problem}', 'parse',
                             1 if mark is None else mark.line,
                             0 if mark is None else mark.column)
            continue
        except yaml.YAMLError as exc:
            yield make_error(f'unknown error parsing YAML: {exc}',
                             'parse', 1, 0)
            continue

        # Run schema validation against the "clean" data, without source
        # location markers.
        pure_data = TrackedLocationLoader.remove_trackers(tagged_data)

        # Basic sanity check.
        if not isinstance(pure_data, dict):
            yield make_error('recipe metadata must be a dictionary '
                             f'(got a {type(pure_data)} instead)',
                             'toplevel-nondict', 1, 0)
            continue

        # Make sure values have the types that they should.
        validator = cerberus.Validator(get_schema_for_file(orig_file_name))
        if not validator.validate(pure_data):
            yield from emit_validation_errors(validator.errors, tagged_data,
                                              orig_file_name,
                                              line_offset, column_offset)

        # Make sure the order of the most important keys is correct.
        yield from check_keys_order(tagged_data, orig_file_name,
                                    line_offset, column_offset)
        for tagged_override_data in tagged_data.get('overrides', {}).values():
            yield from check_keys_order(tagged_override_data, orig_file_name,
                                        line_offset, column_offset)
