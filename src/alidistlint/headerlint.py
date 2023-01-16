"""Internal linter checking YAML headers for alidistlint."""

import re
import os.path
from typing import Any, Iterable

from cerberus import Validator

from alidistlint.common import Error, YAMLFilePart, TrackedLocationLoader, \
    position_of_key

ValidationErrors = list[str | dict[Any, 'ValidationErrors']]
ValidationErrorTree = str | dict[Any, ValidationErrors] | ValidationErrors
"""An error tree as produced by cerberus."""

ObjectPath = tuple[str | int, ...]
"""Specifies where in a nested object a value is located as a series of keys.

For instance, A is at path (0, "a") in the object [{"a": A}].
"""


def get_schema_for_file(file_name: str) -> dict:
    """Construct a schema to validate the YAML header of the given file."""
    def package_name_matches(field, value, error):
        basename = os.path.basename(file_name)
        if not isinstance(value, str):
            error(field, 'must be a string')
        elif f'{value.lower()}.sh' != basename:
            error(field, f'must match the file name {basename!r} '
                  'case-insensitively, excluding the .sh')

    def is_valid_require(field, value, error):
        if not isinstance(value, str):
            error(field, 'must be a string')
            return
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
                'regex': r'^[a-zA-Z_][a-zA-Z0-9_]*$',
            },
            'valuesrules': {
                'anyof': [
                    {'type': 'string'},
                    {'type': 'list', 'schema': {'type': 'string'}},
                ],
            } if allow_list_values else {'type': 'string'},
        }

    def is_valid_version_string(field, value, error):
        if not isinstance(value, str):
            error(field, 'must be a string')
            return

        for match in re.finditer(r'%[^%(]|%$', value):
            error(field, f'invalid substitution type {match.group(0)!r}; '
                  "use only %(...)s (or use '%%' if you want a literal '%')")

        try:
            # The keys listed below all expand to strings normally.
            # Assigning 'placeholder' also catches TypeErrors.
            _ = value % {key: 'placeholder' for key in (
                'branch_basename', 'branch_stream', 'commit_hash',
                'short_hash', 'tag', 'tag_basename', 'defaults_upper',
                'year', 'month', 'day', 'hour',
            )}
        except KeyError as exc:
            error(field, f'substitution variable {exc} is invalid')
        except TypeError:
            error(field, 'invalid substitution type; use only %(...)s')
        except ValueError as exc:
            error(field, f'%-format error: {exc}')

    def is_valid_regex(field, value, error):
        try:
            re.compile(value)
        except re.error as exc:
            error(field, f'invalid regex: {exc}')

    def is_relative_toplevel_path(field, value, error):
        if not isinstance(value, str):
            error(field, 'must be a string')
            return
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
        'version': {'type': 'string', 'check_with': is_valid_version_string},
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
            'check_with': is_valid_version_string,
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
    """Parse any validation errors from a cerberus validator."""
    if isinstance(error_tree, dict):
        for key, suberrors in error_tree.items():
            if re.fullmatch(r'(all|any|none|one)of definition [0-9]+', key):
                subpath = path
            else:
                subpath = path + (key,)
            yield from emit_validation_errors(
                suberrors, tagged_validated_object, file_name,
                line_offset, column_offset, subpath,
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
    """Produce errors relating to key order in the YAML header data."""
    def make_error(message: str, key: str) -> Error:
        rel_line, rel_column = position_of_key(data, (key,))
        return Error('warning', f'{message} [ali:key-order]', orig_file_name,
                     rel_line + line_offset, rel_column + column_offset)

    keys = list(data.keys())
    if 'requires' in data and 'build_requires' in data and \
       keys.index('requires') > keys.index('build_requires'):
        for key in ('requires', 'build_requires'):
            yield make_error('requires must come before build_requires', key)
    if 'package' in data:
        # Top-level (non-override) declaration: the first three keys must be
        # package, version, tag in that order.
        if keys.index('package') != 0:
            yield make_error('package: must be the first key in the file',
                             'package')
        if 'version' in data and keys.index('version') != 1:
            yield make_error('version: must be the second key in the file '
                             '(after package)', 'version')
        if 'tag' in data and keys.index('tag') != 2:
            yield make_error('tag: must be the third key in the file '
                             '(after version)', 'tag')
    elif 'version' in data:
        # Override declaration with a version key: version must be first and
        # tag second (if present).
        if keys.index('version') != 0:
            yield make_error('version: must be the first key in the override '
                             'declaration', 'version')
        if 'tag' in data and keys.index('tag') != 1:
            yield make_error('tag: must be the second key in the override '
                             'declaration (after version)', 'tag')
    elif 'tag' in data and keys.index('tag') != 0:
        # Override declaration without a version key: tag must be first.
        yield make_error('tag: must be the first key in the override '
                         'declaration (as version is not present)', 'tag')


def headerlint(headers: dict[str, YAMLFilePart]) -> Iterable[Error]:
    """Apply alidist-specific linting rules to YAML headers."""
    for header in headers.values():  # we don't need the temporary file
        if header.content is None:
            # This header could not be parsed. We'll have already printed an
            # error message for that.
            continue

        # Make sure values have the types that they should.
        validator = Validator(get_schema_for_file(header.orig_file_name))
        if not validator.validate(
                # Run schema validation against the "clean" data, without
                # source location markers.
                TrackedLocationLoader.remove_trackers(header.content)
        ):
            yield from emit_validation_errors(
                validator.errors, header.content, header.orig_file_name,
                header.line_offset, header.column_offset,
            )

        # Make sure the order of the most important keys is correct.
        yield from check_keys_order(header.content, header.orig_file_name,
                                    header.line_offset, header.column_offset)
        for override_data in header.content.get('overrides', {}).values():
            yield from check_keys_order(override_data, header.orig_file_name,
                                        header.line_offset, header.column_offset)
