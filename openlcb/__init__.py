from enum import Enum
import re
import time

from collections import OrderedDict
from typing import (
    List,  # in case list doesn't support `[` in this Python version
    Union,  # in case `|` doesn't support 'type' in this Python version
)

hex_pairs_re = r"^([0-9A-Fa-f]{2})+$"
hex_pairs_rc = re.compile(hex_pairs_re)
hex_pairs_brc = re.compile(hex_pairs_re.encode("utf-8"))
# {2}: Exactly two characters found (only match if pair)
# +: at least one match plus 0 or more additional matches
ORD_0 = 0x30
ORD_9 = 0x39
ORD_A = 0x41
ORD_F = 0x46
ORD_Z = 0x5A
ORD_a = 0x61
ORD_f = 0x66
ORD_z = 0x7A


def only_hex_pairs(value: str) -> Union[re.Match[bytes], re.Match[str], None]:
    """Check if string contains only machine-readable hex pairs.
    See openlcb.conventions submodule for LCC ID dot notation
    functions (less restrictive).
    """
    if isinstance(value, (bytearray, bytes)):
        return hex_pairs_brc.fullmatch(value)
    assert isinstance(value, str)
    return hex_pairs_rc.fullmatch(value)


def emit_cast(value) -> str:
    """Get type and value, such as for debug output."""
    if value is None:
        return "None"
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


def precise_sleep(seconds: Union[float, int],
                  start: Union[float, None] = None) -> None:
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


def from_hex_bytes(b: bytearray, start: int, stop: int,
                   assertValid=True) -> bytearray:
    """ASCII hex bytearray (even length) → binary bytearray"""
    # like bytearray.fromhex, except accepts bytes rather than str only
    r = bytearray((stop-start) // 2)
    if assertValid:
        if (stop-start) % 2 > 0:
            raise IndexError(
                "Only hex pairs are accepted, got odd count: start={} stop={}"
                .format(start, stop))
        if start < 0 or start > len(b):
            raise IndexError("start={} len={}".format(start, len(b)))
        if stop < 0 or stop > len(b):
            raise IndexError("stop={} len={}".format(start, len(b)))
        if stop - start < 2:
            raise IndexError("start={} stop={}".format(start, stop))
        assert len(r) == (stop - start) // 2
    i = start
    rel = 0
    while i < stop:
        x, y = b[i], b[i+1]
        if assertValid:
            if not ((x >= ORD_A and x <= ORD_F) or (x >= ORD_a and x <= ORD_f) or (x >= ORD_0 and x <= ORD_9)):  # noqa: E501
                raise ValueError("Got character {}, expected hex digit".format((bytearray([x])).decode("utf-8")))  # noqa: E501
            if not ((y >= ORD_A and y <= ORD_F) or (y >= ORD_a and y <= ORD_f) or (y >= ORD_0 and y <= ORD_9)):  # noqa: E501
                raise ValueError("Got character {}, expected hex digit".format((bytearray([y])).decode("utf-8")))  # noqa: E501
        # v =
        # NOTE: below will still raise exception if over 255 even if assertValid is False  # noqa: E501
        r[rel] = ((x & 15) + ((x >> 6) & 1) * 9) << 4 | \
            ((y & 15) + ((y >> 6) & 1) * 9)
        # assert v < 256, str(b[i:i+1])
        # r[rel] = v
        i += 2
        rel += 1
    return r


def from_all_hex_bytes(b: bytearray) -> bytearray:
    return from_hex_bytes(b, 0, len(b))


def hr_repr(value, always_quote: bool = False) -> str:
    """Represent value with double quotes
    (Human-readable repr).
    """
    repr_value = repr(value)
    if repr_value.startswith("'") and repr_value.endswith("'"):
        return '"' + repr_value[1:-1].replace('"', '\\"') + '"'
    elif always_quote:
        return '"' + repr_value.replace('"', '\\"') + '"'
    return repr(value)


def d_quote(value) -> str:
    return hr_repr(value, always_quote=True)
