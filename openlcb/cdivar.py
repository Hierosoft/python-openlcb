
import json
import math

from openlcb import emit_cast
from typing import Any, Type

from openlcb.eventid import EventID
from openlcb.openlcbaction import OpenLCBAction


NUM_TYPES = {'int': int, 'float': float}  # type: dict[str, Type]
# Assumes "IEEE" in LCC CDI Standard means IEEE 754-2008:
FLOAT_MAXIMUMS = {16: 65504.0, 32: 3.40e38, 64: 1.80e308}  # type: dict[int, float]  # noqa: E501
CLASSNAME_TYPES = {'int': int, 'float': float, 'string': str,
                   'blob': bytearray, 'eventid': EventID,
                   'action': OpenLCBAction}


class CDIVar:
    """
    Attributes:
        floatFormat (str): Optional printf-style format
            (for className == "float").
        signed (bool): Whether the value is signed (False unless min is
            negative). Defaults to True.
            See LCC "Configuration Description Information" Standard.
        value (Any): The value read from the device (type should be
            from CLASSNAME_TYPES values).
    """
    TYPED_KEYS = ['min', 'max', 'default']

    def __init__(self, className):
        assert isinstance(className, str), \
            f"Expected {CLASSNAME_TYPES.keys()} got {emit_cast(className)}"
        assert className, f"Expected {CLASSNAME_TYPES.keys()} got {className}"
        assert className in CLASSNAME_TYPES, \
            f"Expected {CLASSNAME_TYPES.keys()} got {className}"
        self.className = className  # type: str
        self.signed = False  # type: bool
        self.value = None  # type: Any
        self.min = None  # type: int|float|None
        self.max = None  # type: int|float|None
        self.default = None  # type: int|float|None
        self.size = None  # type: int|None
        self.floatFormat = None  # type: str|None
