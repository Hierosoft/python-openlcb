from enum import Enum
import re
import time

from collections import OrderedDict
from typing import (
    List,  # in case list doesn't support `[` in this Python version
    Union,  # in case `|` doesn't support 'type' in this Python version
)


hex_pairs_rc = re.compile(r"^([0-9A-Fa-f]{2})+$")
# {2}: Exactly two characters found (only match if pair)
# +: at least one match plus 0 or more additional matches


def only_hex_pairs(value: str) -> bool:
    """Check if string contains only machine-readable hex pairs.
    See openlcb.conventions submodule for LCC ID dot notation
    functions (less restrictive).
    """
    return hex_pairs_rc.fullmatch(value)


def emit_cast(value) -> str:
    """Get type and value, such as for debug output."""
    repr_str = repr(value)
    if isinstance(value, Enum):
        repr_str = "{}".format(value.value)
    if repr_str.startswith(type(value).__name__):
        return repr(value)  # type already included, such as bytearray(...)
    return "{}({})".format(type(value).__name__, repr_str)


def list_type_names(values) -> List[str]:
    """Get the type of several values, such as for debug output.
    Args:
        values (Union[list,tuple,dict,OrderedDict]): A collection where
            each element's type is to be analyzed.

    Raises:
        TypeError: If how to traverse the iterator is unknown (the type
            of `values` is not implemented).

    Returns:
        list[str]: A list where each element is a type name. If
            values argument is dict-like, each element is formatted as
            "{key}: {type}".
    """
    if isinstance(values, (list, tuple)):
        return [type(value).__name__ for value in values]
    if isinstance(values, (dict, OrderedDict)):
        return ["{}: {}".format(k, type(v).__name__) for k, v in values.items()]  # noqa: E501
    raise TypeError("list_type_names is only implemented for"
                    " list, tuple, dict, and OrderedDict, but got a(n) {}"
                    .format(type(values).__name__))


def precise_sleep(seconds: Union[float, int], start: float = None) -> None:
    """Wait for a precise number of seconds
    (precise to hundredths approximately, depending on accuracy of
    platform's sleep). Since time.sleep(seconds) is generally not
    accurate, perf_counter is checked.

    Args:
        seconds (float): Number of seconds to wait.
        start (float, optional): The start time--*must* be a
            time.perf_counter() value. Defaults to time.perf_counter().
    """
    if start is None:
        start = time.perf_counter()
    # NOTE: timeit.default_timer is usually Python 3-only perf_counter
    #   in Python 3
    while (time.perf_counter() - start) < seconds:
        time.sleep(.01)


def formatted_ex(ex) -> str:
    return "{}: {}".format(type(ex).__name__, ex)
