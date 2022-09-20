'''Run alidistlint as a command-line script.'''

from argparse import ArgumentParser, FileType, Namespace
import concurrent.futures
import itertools
import os.path
import queue
import sys
import tempfile
from typing import Callable, Iterable, NoReturn

from alidistlint import common, yamllint, shellcheck, headerlint, scriptlint

Checker = Callable[[Iterable[common.FilePart]], Iterable[common.Error]]


def checker_wrapper(checker: Checker,
                    file_parts: Iterable[common.FilePart],
                    errors_queue: queue.SimpleQueue[common.Error | None]) -> None:
    errors_queue.put(common.Error('info', f'checker {checker} started', '', 0, 0))
    for error in checker(file_parts):
        errors_queue.put(error)
    # Sentinel value. We're done.
    errors_queue.put(common.Error('info', f'checker {checker} done', '', 0, 0))
    errors_queue.put(None)


def run_with_args(args: Namespace) -> int:
    '''Functional script entry point, returning the desired exit code.'''
    formatter = common.ERROR_FORMATTERS[args.format]
    progname = os.path.basename(sys.argv[0])
    have_error = False
    run_functions: list[Checker] = [func for disabled, func in (
        (args.no_headerlint, headerlint.headerlint),
        (args.no_scriptlint, scriptlint.scriptlint),
        (args.no_yamllint, yamllint.yamllint),
        (args.no_shellcheck, shellcheck.shellcheck),
    ) if not disabled]
    errors_queue: queue.SimpleQueue[common.Error | None] = queue.SimpleQueue()

    with tempfile.TemporaryDirectory(prefix=progname) as tempdir:
        iterators = itertools.tee(common.split_files(tempdir, args.recipes),
                                  len(run_functions))

        with concurrent.futures.ThreadPoolExecutor() as executor:
            for func, parts in zip(run_functions, iterators):
                 executor.submit(checker_wrapper, func, parts, errors_queue)

            num_sentinels = 0
            while num_sentinels < len(run_functions):
                if (error := errors_queue.get()) is None:
                    num_sentinels += 1
                    print(f'{num_sentinels}/{len(run_functions)} checkers done')
                else:
                    print(formatter(error), file=sys.stderr)
                    have_error |= error.level == 'error'

    return 1 if have_error else 0


def parse_args() -> Namespace:
    '''Parse and return command-line arguments.'''
    parser = ArgumentParser(description=__doc__, epilog='''\
    Errors and warnings will be printed to standard output in the format you
    selected. If any messages with "error" severity were produced, `%(prog)s`
    exits with a non-zero exit code.
    ''')
    parser.add_argument('-S', '--no-shellcheck', action='store_true',
                        help="don't run shellcheck on the main script")
    parser.add_argument('-Y', '--no-yamllint', action='store_true',
                        help="don't run yamllint on the header")
    parser.add_argument('-H', '--no-headerlint', action='store_true',
                        help="don't run internal linter on the YAML header")
    parser.add_argument('-R', '--no-scriptlint', action='store_true',
                        help="don't run internal linter on any build scripts")
    parser.add_argument('-f', '--format', metavar='FORMAT',
                        choices=common.ERROR_FORMATTERS.keys(), default='gcc',
                        help=('format of error messages '
                              '(one of %(choices)s; default %(default)s)'))
    parser.add_argument('recipes', metavar='RECIPE', nargs='+',
                        type=FileType('rb'),
                        help='a file name to check (use - for stdin)')
    return parser.parse_args()


def main() -> NoReturn:
    '''Script entry point; parse args, run and exit.'''
    sys.exit(run_with_args(parse_args()))
