
import base64
from collections import OrderedDict
import copy
import struct

from logging import getLogger
from typing import Any, List, Type, Union

from openlcb import emit_cast
from openlcb.eventid import EventID
from openlcb.openlcbaction import OpenLCBAction

logger = getLogger(__name__)

NUM_TYPES = {'int': int, 'float': float}  # type: dict[str, Type]
# Assumes "IEEE" in OpenLCB CDI Standard means IEEE 754-2008:
FLOAT_MAXIMUMS = {16: 65504.0, 32: 3.40e38, 64: 1.80e308}  # type: dict[int, float]  # noqa: E501
CLASSNAME_TYPES = {'int': int, 'float': float, 'string': str,
                   'blob': bytearray, 'eventid': EventID,
                   'action': OpenLCBAction}
SIZED_CONSTRUCTION_TYPES = copy.deepcopy(CLASSNAME_TYPES)
SIZED_CONSTRUCTION_TYPES['eventid'] = bytearray
SUBTYPE_FORMATS = {
    'int8': "b", 'uint8': "B",
    'int16': ">h", 'uint16': ">H",
    'int32': ">i", 'uint32': ">I",
    'int64': ">q", 'uint64': ">Q",
    'float16': ">e",
    'float32': ">f",
    'float64': ">d",
}
STANDARD_SIZES = {
    'int': (1, 2, 4, 8),
    'float': (2, 4, 8),
    'eventid': (8,),
    'action': (1, 2, 4, 8),
}


class CDIVar:
    """A byte array representing a single configuration variable.
    Arguments:
        _default (bytearray): An array with length matching size.
        _min (int): Minimum value (only for int/float className. <0 sets
            .signed = True)
        _max (int): Maximum value (only for int/float className)
        _size (int): Size of int/float (not allowed for other className).

    Attributes:
        className (str): An OpenLCB CDI type. Must be a key in
            CLASSNAME_TYPES.
        floatFormat (str): Optional printf-style format
            (for className == "float").
        signed (bool): Whether the value is signed (False unless min is
            negative). Defaults to True.
            See OpenLCB "Configuration Description Information" Standard.
        _data (bytes): The value read from the device or ready to
            write. Only None if not read yet, otherwise length
            must be .size.
        element (xml.etree.Element): An associated element in an XML
            tree.
    """
    TYPED_KEYS = ['min', 'max', 'default']

    def __init__(self, className, _min=None, _max=None,
                 _size=None, _default=None):
        assert isinstance(className, str), \
            f"Expected {CLASSNAME_TYPES.keys()} got {emit_cast(className)}"
        assert className, f"Expected {CLASSNAME_TYPES.keys()} got {className}"
        assert className in CLASSNAME_TYPES, \
            f"Expected {list(CLASSNAME_TYPES.keys())} got {className}"
        self.name = None  # type: str|None
        self.className = className  # type: str
        self.data = None  # type: bytes|None
        self.min = _min  # type: int|float|None
        self.signed = False  # type: bool
        if self.min and self.min < 0:
            self.signed = True
        self.max = _max  # type: int|float|None
        self.default = _default  # type: bytearray|None
        self.size = _size  # type: int|None
        self.branch_size = None  # type: int|None  # size including children
        if self.size is None:
            if self.default is not None:
                self.size = len(self.default)
        if self.className in ("int", "float"):
            self.assertNumberFormat()
        elif self.className == "eventid":
            if (_size is not None) and (_size != 8):
                logger.error(
                    f'Specified eventid size="{_size}" but 8 is required.')
            self.size = 8
        sizes = STANDARD_SIZES.get(self.className)
        if sizes is not None:
            assert self.size in sizes, \
                (f"Expected size in {sizes}"
                 f" for {self.className} but got {self.size}")
        self.floatFormat = None  # type: str|None
        self.address = None  # type: int|None
        self.element = None  # type: Any|None
        self.space = None  # type: int|None

    def setData(self, data: Union[bytes, bytearray]):
        assert isinstance(data, (bytes, bytearray))
        if isinstance(data, bytes):
            data = bytearray(data)
        if self.className == "eventid":
            assert len(data) == 8
        elif self.className == "blob":
            # FIXME: enforce blob
            pass
        elif self.className == "string":
            assert self.size
            assert len(data) <= self.size
        elif self.className in SIZED_CONSTRUCTION_TYPES:
            assert self.size
            assert len(data) == self.size
        else:
            raise NotImplementedError(f"Type {self.className} not implemented")
        self.data = data

    def getData(self):
        return self.data

    def isNumber(self):
        return self.className in ("int", "float")

    def standardSizes(self) -> Union[List[int], None]:
        return STANDARD_SIZES.get(self.className)

    def assertNumberFormat(self, assertWhat=""):
        if self.className == "int":
            assert self.size in (1, 2, 4, 8), \
                f"Expected size (1, 2, 4, 8) for int, got {self.size}"
        elif self.className == "float":
            assert self.size in (2, 4, 8), \
                f"Expected size (2, 4, 8) for float, got {self.size}"
        else:
            if not assertWhat:
                assertWhat = f"Expected float/int size {STANDARD_SIZES}"
            raise TypeError(
                f"{assertWhat}"
                f", but cdivar is {self.className} size={self.size}")

    def bitDepth(self) -> int:
        self.assertNumberFormat(assertWhat="Only float/int has bitDepth")
        return self.size * 8  # type:ignore (assert precludes bad size)

    def subtype(self) -> str:
        """Get the number subtype in C++-like notation.

        Returns:
            str: Key for SUBTYPE_FORMATS.

        Raises:
            TypeError: (raised by bitDepth) if not int 8-64 bit, and not
                float 16-64 bit.
        """
        prefix = ""
        if self.className == "int" and not self.signed:
            prefix = "u"
        return f"{prefix}{self.className}{self.bitDepth()}"

    def packFormat(self) -> str:
        assert self.className in ("int", "float"), \
            f"Can only pack if isNumber, but this cdivar is {self.className}"
        return SUBTYPE_FORMATS[self.subtype()]

    def intToData(self, value: int) -> bytes:
        assert self.className == "int"
        assert isinstance(value, int)
        return struct.pack(self.packFormat(), value)

    def getSerializable(self):
        """Get a value in the corresponding Python type"""
        if self.className == "int":
            return self.getInt()
        elif self.className == "float":
            return self.getFloat()
        elif self.className == "string":
            return self.getString()
        assert self.className in ("blob", "eventid", "action")
        return base64.b64encode(self.data)

    def getDict(self, add_name=True):
        result = OrderedDict()
        if add_name and self.name:
            result['name'] = self.name
        result['className'] = self.className
        result['value'] = self.getSerializable()
        return result

    def setInt(self, value: int):
        self.data = self.intToData(value)

    def floatToData(self, value: float) -> bytes:
        assert self.className == "float", \
            f"floatToData attempted on non-float: {self.className}"
        assert isinstance(value, float)
        return struct.pack(self.packFormat(), value)

    def setFloat(self, value: float):
        self.data = self.floatToData(value)

    def stringToData(self, value: str) -> bytes:
        assert self.className == "string"
        assert isinstance(value, str)
        return value.encode("utf-8")

    def setString(self, value: str):
        # self.data = self.stringToData(value)
        # self.size = len(self.data)
        # assert self.className == "string"
        encoded = value.encode("utf-8")
        assert self.size is not None
        assert len(encoded) + 1 <= self.size  # size is max *only* if "string"
        self.data = encoded + b"\x00"  # null-terminated for OpenLCB network

    def dataToInt(self, data) -> Union[int, None]:
        assert self.className == "int"
        if (data is None) or (len(data) < 1):
            return None
        assert self.size == len(data)
        # [0] since always returns list (and there is only one as per
        #   Standard and the assertion above):
        return struct.unpack(self.packFormat(), data)[0]

    def getInt(self) -> Union[int, None]:
        return self.dataToInt(self.data)

    def dataToFloat(self, data) -> Union[float, None]:
        assert self.className == "float"
        if (data is None) or (len(data) < 1):
            return None
        assert self.size == len(data)
        # [0] since always returns list (and there is only one as per
        #   Standard and the assertion above):
        return struct.unpack(self.packFormat(), data)[0]

    def getFloat(self) -> Union[float, None]:
        return self.dataToFloat(self.data)

    def dataToString(self, data) -> Union[str, None]:
        assert self.className == "string"
        if (data is None) or (len(data) < 1):
            return None
        return data.decode("utf-8")

    def getString(self) -> Union[str, None]:
        # return self.dataToString(self.data)
        if self.data is None or len(self.data) == 0:
            return None
        # Return content up to (but not including) first null
        null_pos = self.data.find(b"\x00")
        if null_pos == -1:
            logger.error(f"No null terminator in {repr(self.data)}")
            content = self.data
        else:
            content = self.data[:null_pos]
        # try:
        return content.decode("utf-8")
        # except UnicodeDecodeError:
        #     return None  # or raise
