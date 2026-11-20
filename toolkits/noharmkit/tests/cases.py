from collections.abc import Callable, Iterable
from typing import TypeVar

T = TypeVar("T")


def each_case(cases: Iterable[T], name: Callable[[T], str], run: Callable[[T], object]) -> None:
    """Run every row of a table-driven test inside one test and name the failing row."""
    for case in cases:
        try:
            run(case)
        except BaseException as error:  # pytest.fail raises a BaseException subclass
            error.add_note(f'Row "{name(case)}"')
            raise
