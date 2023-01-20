#!/usr/bin/env python3

"""Lint alidist recipes using yamllint and shellcheck."""

import os.path
from typing import BinaryIO, Callable, Iterable, NamedTuple, Sequence

import yaml

GCC_LEVELS: dict[str, str] = {
    'error': 'error',
    'warning': 'warning',
    'info': 'note',
    'style': 'note',
}

GITHUB_LEVELS: dict[str, str] = {
    'error': 'error',
    'warning': 'warning',
    'info': 'notice',
    'style': 'notice',
}


class YAMLFilePart(NamedTuple):
    """Metadata for a part of a file to be checked.

    This contains metadata for the YAML header, and the header itself, as a
    parsed YAML object, or None if the YAML header could not be parsed.
    """
    orig_file_name: str
    line_offset: int
    column_offset: int
    content: dict | None


class ScriptFilePart(NamedTuple):
    """A script part of an alidist recipe.

    This contains metadata of the script, the script text itself, and
    additional information parsed from any associated YAML header. This
    additional information is used for 'scriptlint' checks.
    """
    orig_file_name: str
    line_offset: int
    column_offset: int
    content: bytes
    key_name: str | None   # None means "this is the main recipe"
    is_system_requirement: bool


class Error(NamedTuple):
    """A linter message.

    Instances should contain line and column numbers relative to the original
    input file, not relative to any FileParts that might have been used.
    """

    level: str
    message: str
    file_name: str
    line: int
    column: int
    end_line: int | None = None
    end_column: int | None = None

    def format_gcc(self) -> str:
        """Turn the Error into a string like a GCC error message."""
        return (f'{self.file_name}:{self.line}:{self.column}: '
                f'{GCC_LEVELS[self.level]}: {self.message}')

    def format_github(self) -> str:
        """Turn the Error into a string that GitHub understands.

        If printed from a GitHub Action, this will show the error messages in
        the Files view.
        """
        end_line = '' if self.end_line is None else f',endLine={self.end_line}'
        end_column = '' if self.end_column is None else \
            f',endColumn={self.end_column}'
        return (f'::{GITHUB_LEVELS[self.level]} file={self.file_name}'
                f',line={self.line}{end_line}'
                f',col={self.column}{end_column}::{self.message}')


ERROR_FORMATTERS: dict[str, Callable[[Error], str]] = {
    'gcc': Error.format_gcc,
    'github': Error.format_github,
}


# pylint: disable=too-many-ancestors
class TrackedLocationLoader(yaml.loader.SafeLoader):
    """Load YAML documents while keeping track of keys' line and column.

    We need to override construct_sequence to track the location of list items,
    and construct_mapping to track the location of keys.

    See also: https://stackoverflow.com/q/13319067
    """

    def construct_sequence(self, node, deep=False):
        """Construct a sequence, storing the source locations of its values."""
        sequence = super().construct_sequence(node, deep)
        sequence.append([item_node.start_mark for item_node in node.value])
        return sequence

    def construct_mapping(self, node, deep=False):
        """Construct a mapping, storing the source locations of its keys."""
        mapping = super().construct_mapping(node, deep=deep)
        mapping['_locations'] = {
            # Keys aren't necessarily strings, so parse them in YAML.
            self.construct_object(key_node): key_node.start_mark
            for key_node, _ in node.value
        }
        return mapping

    @staticmethod
    def remove_trackers(data):
        """Remove temporary location tracker items.

        Original file locations are tracked using special properties and list
        items and used for more informative error messages, but they should not
        be present for schema validation, for example.
        """
        if isinstance(data, dict):
            return {key: TrackedLocationLoader.remove_trackers(value)
                    for key, value in data.items()
                    if key != '_locations'}
        if isinstance(data, list):
            return [TrackedLocationLoader.remove_trackers(value)
                    for value in data[:-1]]
        return data


def parse_yaml_header_tagged(yaml_text: bytes, orig_file_name: str,
                             line_offset: int, column_offset: int) \
                             -> dict | Error:
    """Parse the given YAML header text, checking for basic sanity."""
    if not yaml_text:
        return Error('error', 'metadata not found or empty (is the '
                     "'\\n---\\n' separator present?) [ali:empty]",
                     orig_file_name, line_offset + 1, column_offset)

    # Parse the source YAML, keeping track of the locations of keys.
    try:
        parsed_yaml = yaml.load(yaml_text, TrackedLocationLoader)
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark
        return Error('error', f'YAML parse error: {exc.problem} [ali:parse]',
                     orig_file_name,
                     1 if mark is None else mark.line,
                     0 if mark is None else mark.column)
    except yaml.YAMLError as exc:
        return Error('error', f'unknown YAML parse error: {exc} [ali:parse]',
                     orig_file_name, line_offset + 1, column_offset)

    # We expect a dictionary here.
    if not isinstance(parsed_yaml, dict):
        return Error('error', 'expected YAML header to be a dictionary; got a '
                     f'{type(parsed_yaml).__name__} instead [ali:parse]',
                     orig_file_name, line_offset + 1, column_offset)
    return parsed_yaml


def split_files(temp_dir: str, input_files: Iterable[BinaryIO]) \
        -> tuple[Sequence[Error],
                 dict[str, YAMLFilePart],
                 dict[str, ScriptFilePart]]:
    """Split every given file into its YAML header and script part."""
    errors: list[Error] = []
    header_parts: dict[str, YAMLFilePart] = {}
    script_parts: dict[str, ScriptFilePart] = {}
    for input_file in input_files:
        orig_basename = os.path.basename(input_file.name)
        recipe = input_file.read()
        # Get the first byte of the '---\n' line (excluding the prev newline).
        separator_position = recipe.find(b'\n---\n') + 1
        # If the separator isn't present, yaml_text will be empty.
        # parse_yaml_header_tagged checks for this.
        yaml_text = recipe[:separator_position]

        # aliBuild splits header from recipe on '---', NOT '\n---\n'! This
        # means we must not have any '---' string anywhere in the YAML header.
        if b'---' in yaml_text:
            for lineno, line in enumerate(yaml_text.splitlines()):
                dashes_pos = line.find(b'---')
                if dashes_pos != -1:
                    errors.append(Error(
                        'error', 'found "---" in YAML header; this prevents '
                        'aliBuild from parsing this recipe [ali:parse]',
                        input_file.name, lineno + 1,
                        column=dashes_pos + 1, end_column=dashes_pos + 4,
                    ))

        parsed_yaml = parse_yaml_header_tagged(yaml_text, input_file.name, 0, 0)
        if isinstance(parsed_yaml, Error):
            errors.append(parsed_yaml)
            parsed_yaml = None

        # Extract the complete YAML header and store it for later parsing.
        with open(f'{temp_dir}/{orig_basename}.head.yaml', 'wb') as headerf:
            headerf.write(yaml_text)
            header_parts[headerf.name] = \
                YAMLFilePart(input_file.name, 0, 0, parsed_yaml)

        is_system_requirement: bool = \
            parsed_yaml is not None and 'system_requirement' in parsed_yaml

        # Extract the main recipe script.
        with open(f'{temp_dir}/{orig_basename}.script.sh', 'wb') as scriptf:
            script = recipe[separator_position + 4:]
            scriptf.write(script)
            script_parts[scriptf.name] = ScriptFilePart(
                # Add 1 to line offset for the separator line.
                input_file.name, yaml_text.count(b'\n') + 1, 0, script, None,
                is_system_requirement,
            )

        # Extract recipes embedded in YAML header, e.g. incremental_recipe.
        if parsed_yaml is None:
            continue
        for recipe_key, recipe in parsed_yaml.items():
            if not isinstance(recipe_key, str):
                continue
            if not (recipe_key.endswith('_recipe') or
                    recipe_key.endswith('_check')):
                continue
            line_offset, column_offset = position_of_key(parsed_yaml,
                                                         (recipe_key,))
            line_offset += 1     # assume values start on a new line
            line_offset -= 1     # first line is 1, but this is an offset
            column_offset += 2   # yamllint requires 2-space indents
            column_offset -= 1   # first column is 1, but this is an offset
            if not isinstance(recipe, str):
                errors.append(Error(
                    'error', 'script must be a string, not a '
                    f'{type(recipe).__name__} [ali:script-type]',
                    input_file.name, line_offset, column_offset,
                ))
                continue
            with open(f'{temp_dir}/{orig_basename}.{recipe_key}.sh', 'w',
                      encoding='utf-8') as scriptf:
                scriptf.write(recipe)
                script_parts[scriptf.name] = ScriptFilePart(
                    input_file.name, line_offset, column_offset,
                    recipe.encode('utf-8'), recipe_key, is_system_requirement,
                )

    return errors, header_parts, script_parts


def position_of_key(tagged_object: dict,
                    path: tuple[str | int, ...]) -> tuple[int, int]:
    """Find the line and column numbers of the specified key."""
    cur_object_parent = tagged_object
    for path_element in path[:-1]:
        cur_object_parent = cur_object_parent[path_element]
    if isinstance(cur_object_parent, dict):
        direct_parent = cur_object_parent['_locations']
    elif isinstance(cur_object_parent, list):
        direct_parent = cur_object_parent[-1]
    else:
        raise TypeError(f'expected dict or list; got {cur_object_parent!r} '
                        f'of type {type(cur_object_parent).__name__}')
    try:
        mark = direct_parent[path[-1]]
        return mark.line + 1, mark.column + 1
    except KeyError:
        # The key is not present, but probably required.
        return 1, 0
