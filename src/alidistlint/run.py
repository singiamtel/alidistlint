"""Run alidistlint as a command-line script."""

from argparse import ArgumentParser, FileType, Namespace
import itertools
import os.path
import sys
import tempfile
from typing import NoReturn

from alidistlint import common, scriptlint, yamllint, shellcheck, headerlint


def run_with_args(args: Namespace) -> int:
    """Functional script entry point, returning the desired exit code."""
    formatter = common.ERROR_FORMATTERS[args.format]
    progname = os.path.basename(sys.argv[0])
    have_error = False
    with tempfile.TemporaryDirectory(prefix=progname) as tempdir:
        errors, headers, scripts = common.split_files(tempdir, args.recipes)
        errors = itertools.chain(
            errors,
            () if args.no_headerlint else headerlint.headerlint(headers),
            () if args.no_scriptlint else scriptlint.scriptlint(scripts),
            () if args.no_yamllint else yamllint.yamllint(headers),
            () if args.no_shellcheck else shellcheck.shellcheck(scripts),
        )
        for error in errors:
            print(formatter(error))
            have_error |= error.level == 'error'
    return 1 if have_error else 0


def parse_args() -> Namespace:
    """Parse and return command-line arguments."""
    parser = ArgumentParser(description=__doc__, epilog='''\
    Errors and warnings will be printed to standard output in the format you
    selected. If any messages with "error" severity were produced,
    `alidistlint` exits with a non-zero exit code.
    ''')
    parser.add_argument('-S', '--no-shellcheck', action='store_true',
                        help="don't run shellcheck on each script")
    parser.add_argument('-L', '--no-scriptlint', action='store_true',
                        help="don't run internal linter on each script")
    parser.add_argument('-Y', '--no-yamllint', action='store_true',
                        help="don't run yamllint on the YAML header")
    parser.add_argument('-H', '--no-headerlint', action='store_true',
                        help="don't run internal linter on the YAML header")
    parser.add_argument('-f', '--format', metavar='FORMAT',
                        choices=common.ERROR_FORMATTERS.keys(), default='gcc',
                        help=('format of error messages '
                              '(one of %(choices)s; default %(default)s)'))
    parser.add_argument('recipes', metavar='RECIPE', nargs='+',
                        type=FileType('rb'),
                        help='a file name to check (use - for stdin)')
    return parser.parse_args()


def main() -> NoReturn:
    """Script entry point; parse args, run and exit."""
    sys.exit(run_with_args(parse_args()))
