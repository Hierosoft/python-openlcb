
import base64
from collections import OrderedDict
import copy
from enum import Enum
import struct

from logging import getLogger
from typing import Any, List, Type, Union

from openlcb import emit_cast, formatted_ex
from openlcb.eventid import EventID
from openlcb.openlcbaction import OpenLCBAction

logger = getLogger(__name__)

NUM_TYPES = {'int': int, 'float': float}  # type: dict[str, Type]
# Assumes "IEEE" in OpenLCB CDI Standard means IEEE 754-2008:
FLOAT_MAXIMUMS = {2: 65504.0, 4: 3.40e38, 8: 1.80e308}  # type: dict[int, float]  # noqa: E501
# Float minimums (https://en.wikipedia.org/wiki/IEEE_754):
# 16-bit smallest normal 6.10×10−5 subnormal 5.96×10−8
# 32-bit smallest normal 1.18×10−38 subnormal 1.40×10−45
# 64-bit smallest normal 2.23×10−308 subnormal 4.94×10−324
F_MIN_BITS = {
    2: [0] * 16,
    4: [0] * 32,
    8: [0] * 64,
}

# Set bits for the most negative finite number
for size, bits in F_MIN_BITS.items():
    bits[0] = 1                                 # Sign bit = 1 (negative)
    if size == 2:      # binary16: 1 sign + 5 exp + 10 mant
        for i in range(1, 6):   bits[i] = 1    # exp = 11110
        bits[5] = 0                             # ← important: clear LSB of exponent
        for i in range(6, 16):  bits[i] = 1    # mantissa all 1s
    elif size == 4:    # binary32: 1 sign + 8 exp + 23 mant
        for i in range(1, 9):   bits[i] = 1    # exp = 11111110
        bits[8] = 0                             # ← clear LSB of exponent
        for i in range(9, 32):  bits[i] = 1
    else:              # binary64: 1 sign + 11 exp + 52 mant
        for i in range(1, 12):  bits[i] = 1    # exp = 111...1110
        bits[11] = 0                            # ← clear LSB of exponent
        for i in range(12, 64): bits[i] = 1

FLOAT_MINIMUMS = {}  # F_MIN_DATA = {}

for k, bits in F_MIN_BITS.items():
    # Create traceable binary string (e.g. "0b000...001")
    bit_str = "0b" + "".join(map(str, bits))
    # Convert to integer then to bytes
    value = int(bit_str, 2)
    data_bytes = value.to_bytes(k, 'big')
    fmt = {2: ">e", 4: ">f", 8: ">d"}[k]
    # F_MIN_DATA[k] = data_bytes 
    FLOAT_MINIMUMS[k] = struct.unpack(fmt, data_bytes)[0]
    # print(f"binary{k*8:2d} bits: {bit_str}")
    # print(f"binary{k*8:2d} value: {F_MIN_DATA[k]:.20e}\n")
    # results:
    # -65504.0
    # -3.4028234663852886e+38
    # -1.7976931348623157e+308

UNSIGNED_INT_MAXIMUMS = {  # type: dict[int, int]
    1: 0xFF, 2: 0xFFFF, 4: 0xFFFF_FFFF, 8: 0xFFFF_FFFF_FFFF_FFFF}
SIGNED_INT_MINIMUMS = {}
SIGNED_INT_MAXIMUMS = {}
for k, v in UNSIGNED_INT_MAXIMUMS.items():
    SIGNED_INT_MINIMUMS[k] = - ((v + 1) // 2)  # - is 1 further from 0 than +
    SIGNED_INT_MAXIMUMS[k] = v // 2  # floor div removes the extra from odd #
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


class CompareOp(Enum):
    LessThan = -1
    EqualTo = 0
    GreaterThan = 1


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
        assert_range (bool): raise AssertionError if default
            is out of range, such as for tests, instead of
            showing an error. Defaults to False (fault-tolerant
            to avoid crash for malformed CDI).
        _no_min (bool): For internal use only (Prevent infinite
            recursion of the constructor when constructing CDIVar for a
            standard default).
        _no_max (bool): For internal use only (Prevent infinite
            recursion of the constructor when constructing CDIVar for a
            standard default).
    """
    TYPED_KEYS = ['min', 'max', 'default']

    def __init__(self, className, _min=None, _max=None,
                 _size=None, _default=None, assert_range=False,
                 _no_min=False, _no_max=False, _default_data=None,
                 signed=None):
        self.data = None  # type: bytes|None
        self.min = _min  # type: CDIVar|None
        self.max = _max  # type: CDIVar|None

        assert isinstance(className, str), \
            f"Expected {CLASSNAME_TYPES.keys()} got {emit_cast(className)}"
        assert className, f"Expected {CLASSNAME_TYPES.keys()} got {className}"
        assert className in CLASSNAME_TYPES, \
            f"Expected {list(CLASSNAME_TYPES.keys())} got {className}"
        if _default is not None:
            assert isinstance(_default, CDIVar)
            assert _default_data is None, \
                "Can only set _default or _default_data"
        elif _default_data is not None:
            if isinstance(_default_data, bytes):
                _default_data = bytearray(_default_data)
            assert isinstance(_default_data, bytearray)
            _default = CDIVar(className, _size=_size,
                              _no_max=True, _no_min=True)  # prevent recursion
            _default.data = _default_data

        if _default is not None:
            if className in NUM_TYPES:
                _default.assertNumberFormat()
                if _default < 0:
                    if signed is None:
                        signed = True

        self.name = None  # type: str|None
        self.className = className  # type: str
        if signed is None:
            signed = False
        self.signed = signed  # type: bool
        assert isinstance(_no_min, bool)
        assert isinstance(_no_max, bool)
        self._no_min = _no_min
        self._no_max = _no_max
        thisType = CLASSNAME_TYPES.get(className)
        num_types = tuple(NUM_TYPES.values())
        if _min is not None:
            assert isinstance(_min, CDIVar)
            _min.assertNumberFormat()
            assert thisType is not None
            min_value = _min.value()
            assert isinstance(min_value, thisType)
            assert isinstance(min_value, num_types)  # types valid for min
            assert isinstance(min_value, (int, float))  # types valid for min
            # ^ assert (int, float) to help (Pylance) linting of comparisons
            if min_value and min_value < 0:
                self.signed = True
            if _default is not None:
                if _default < _min:
                    error = f"default for {_default} < min {_min}"
                    if assert_range:
                        raise AssertionError(error)
                    else:
                        logger.error(error)
        elif (className in NUM_TYPES) and not _no_min:
            # self.min = CDIVar(className, _size=_size,
            #                   _no_min=True, _no_max=True)  # prevent inf recurs
            # Set minimum based on size,
            #   as per Configuration Description Information Standard.
            assert _size is not None
            if className == "int":
                if signed:
                    # self.min.setInt(SIGNED_INT_MINIMUMS[_size])
                    self.min = CDIVar.fromInt(SIGNED_INT_MINIMUMS[_size],
                                              _size)
                else:
                    # self.min.setInt(0)
                    self.min = CDIVar.fromInt(0, _size)
            elif className == "float":
                # self.min.setFloat(FLOAT_MINIMUMS[_size])
                self.min = CDIVar.fromFloat(FLOAT_MINIMUMS[_size], _size)
            else:
                raise NotImplementedError(f"no default minimum {className}")

        if _max is not None:
            assert isinstance(_max, CDIVar)
            _max.assertNumberFormat()
            assert thisType is not None
            max_value = _max.value()
            assert isinstance(max_value, thisType)
            assert isinstance(max_value, num_types)  # types valid for max
            if _default is not None:
                if _default > self.max:
                    error = f"default for {_default} > max {self.max}"
                    if assert_range:
                        raise AssertionError(error)
                    else:
                        logger.error(error)
        elif (className in NUM_TYPES) and not _no_max:
            assert isinstance(_size, int)
            self.max = CDIVar(className, _size=_size,
                              _no_min=True, _no_max=True)  # prevent inf recur
            if className == "int":
                if self.signed:
                    self.max.setInt(SIGNED_INT_MAXIMUMS[_size])
                else:
                    self.max.setInt(UNSIGNED_INT_MAXIMUMS[_size])
            elif className == "float":
                self.max.setFloat(FLOAT_MAXIMUMS[_size])
            else:
                NotImplementedError()
            if _default is not None:
                if _default > self.max:
                    logger.error(f"default for {_default} > max {self.max}")
        self.default = _default  # type: CDIVar|None
        self.size = _size  # type: int|None
        self.branch_size = None  # type: int|None  # size including children
        if self.size is None:
            if className == "eventid":
                self.size = 8
            else:
                raise ValueError(f"size must be specified for {className}")
            # elif self.default is not None:
            #     self.size = len(self.default.data)
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

    @staticmethod
    def cmp_float(left: 'CDIVar', right: Union['CDIVar', float]) -> CompareOp:
        assert left.className == "float"
        l_value = left.getFloat()
        assert l_value is not None
        if isinstance(right, (float, int)):
            # ^ int is only allowed since Python reverts 0 or 1 etc to int
            r_value = right
        else:
            assert isinstance(right, CDIVar)
            assert left.className == right.className
            r_value = right.getFloat()
            assert r_value is not None
        if l_value < r_value:
            return CompareOp.LessThan
        elif l_value > r_value:
            return CompareOp.GreaterThan
        return CompareOp.EqualTo

    @staticmethod
    def cmp_int(left: 'CDIVar', right: Union['CDIVar', int]) -> CompareOp:
        assert left.className == "int"
        l_value = left.getInt()
        assert l_value is not None
        if isinstance(right, int):
            r_value = right
        else:
            assert isinstance(right, CDIVar)
            assert left.className == right.className
            r_value = right.getInt()
            assert r_value is not None
        if l_value < r_value:
            return CompareOp.LessThan
        elif l_value > r_value:
            return CompareOp.GreaterThan
        return CompareOp.EqualTo

    def __le__(self, other):
        return (self < other) or (self == other)

    def __ge__(self, other):
        return (self > other) or (self == other)

    def __add__(self, other):
        if isinstance(other, float):
            assert self.className == "float"
            return self._getFloat() + other
        elif isinstance(other, int):
            assert self.className == "int"
            return self._getInt() + other
        else:
            assert isinstance(other, CDIVar)
            assert self.className == other.className
            if self.className == "float":
                return self._getFloat() + other._getFloat()
            elif self.className == "int":
                return self._getInt() + other._getInt()
        raise TypeError(
            f"Cannot add {self.className} CDIVar and {type(other).__name__}")

    def __sub__(self, other):  # required by assertAlmostEqual
        if isinstance(other, (int, float)):
            value = self + (-other)
            assert isinstance(value, (int, float))
            return value
        assert isinstance(other, CDIVar)
        assert self.className == other.className
        if self.className == "int":
            return self._getInt() + other._getInt()
        if self.className == "float":
            return self._getFloat() + other._getFloat()
        raise TypeError(
            f"Cannot '-' {self.className} CDIVar and {type(other).__name__}")

    def __eq__(self, other):
        if self.className == "string":
            # Don't carelessly compare data in case a
            #   null-terminated string has junk after it.
            if isinstance(other, str):
                return self.getString() == other
            assert isinstance(other, CDIVar)
            return self.getString() == other.getString()
        assert not isinstance(other, str)
        r_value = other
        if isinstance(other, CDIVar):
            assert self.className == other.className
            if self.size != other.size:
                if self.className == "int":
                    r_value = other.getInt()
                elif self.className == "float":
                    r_value = other.getFloat()
                else:
                    assert self.className not in NUM_TYPES, \
                        f"comparing value of {self.className} not implemented"
                    return False
                assert r_value is not None
        if self.className in NUM_TYPES:
            return type(self).cmp_any(self, r_value, CompareOp.EqualTo)
        return self.data == other.data
        # return type(self).cmp_any(self, other, CompareOp.EqualTo)

    def __gt__(self, other):
        return type(self).cmp_any(self, other, CompareOp.GreaterThan)

    def __lt__(self, other):
        return type(self).cmp_any(self, other, CompareOp.LessThan)

    def __str__(self):
        return str(self.value())

    def __repr__(self):
        return repr(self.value())

    @classmethod
    def cmp_any(cls, self: 'CDIVar', other: Union['CDIVar', float, int],
                compare_op: CompareOp):
        if isinstance(other, CDIVar):
            assert self.className == other.className, \
                f"Cannot compare {self.className} to {other.className} CDIVars"
            if self.className == "float":
                return self.cmp_float(self, other) == compare_op
            elif self.className == "int":
                return self.cmp_int(self, other) == compare_op
            else:
                raise TypeError(
                    f"Can only compare value types, got {self.className}")
        elif isinstance(other, float):
            assert self.className == "float", \
                f"Can't compare float to {self.className} CDIVar"
            return self.cmp_float(self, other) == compare_op
        elif isinstance(other, int):
            assert self.className == "int", \
                f"Can't compare int to {self.className} CDIVar"
            return self.cmp_int(self, other) == compare_op
        else:
            raise TypeError(
                f"Cannot compare {type(other).__name__}"
                f" to CDIVar with {compare_op}")

    @classmethod
    def fromNumber(cls, value: Union[int, float],
                   className: str, _size: int) -> 'CDIVar':
        var = CDIVar(className, _size=_size, _no_min=True)
        # ^ _no_min prevents infinite recursion generating min
        if value < 0:
            var.signed = True
            var.min = None  # remove default (0)
        if className == "int":
            assert isinstance(value, int)
            var.setInt(value)
        elif className == "float":
            assert isinstance(value, (int, float))
            # ^ int is allowed only since in Python an int literal such
            #   as 0 or 1 is common in place of float.
            var.setFloat(value)
        else:
            raise TypeError(
                f"fromNumber requires {list(NUM_TYPES.keys())}"
                f" but got {className} for className")
        return var

    @classmethod
    def fromInt(cls, value: int, _size: int) -> 'CDIVar':
        return cls.fromNumber(value, "int", _size)

    @classmethod
    def fromFloat(cls, value: float, _size: int) -> 'CDIVar':
        return cls.fromNumber(value, "float", _size)

    @classmethod
    def fromString(cls, value: str, _size: int) -> 'CDIVar':
        var = CDIVar(className="string", _size=_size)
        return var

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

    def set(self, other: Union['CDIVar', int, float]):
        assert isinstance(other, (CDIVar, int, float, str))
        if isinstance(other, CDIVar):
            assert self.className == other.className, \
                f"tried to set {self.className} using {other.className}"
            if self.className == "int":
                r_value = other.getInt()
                assert r_value is not None
                if self.min is not None:
                    assert r_value >= self.min
                if self.max is not None:
                    assert r_value <= self.max
                self.setInt(r_value)
            elif self.className == "float":
                r_value = other.getFloat()
                assert r_value is not None
                if self.min is not None:
                    assert r_value >= self.min
                if self.max is not None:
                    assert r_value <= self.max
                self.setFloat(r_value)
            else:
                assert self.className not in NUM_TYPES, \
                    f"bounds check not implemented for {self.className}"
                # No bounds checking necessary
                self.data = copy.deepcopy(other.data)
        else:
            assert isinstance(other, CLASSNAME_TYPES[self.className]), \
                f"Tried to set {self.className} to a(n) {type(other).__name__}"
            if self.className == "int":
                assert isinstance(other, int)  # for linter (Pylance)
                self.setInt(other)  # asserts type as well
            elif self.className == "float":
                assert isinstance(other, float)  # for linter (Pylance)
                self.setFloat(other)  # asserts type as well
            else:
                raise NotImplementedError(
                    f"Tried to set {self.className} to a(n)"
                    f" {type(other).__name__}")

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
        try:
            return struct.pack(self.packFormat(), value)
        except Exception as ex:
            logger.error("")
            logger.error(formatted_ex(ex))
            logger.error(
                f"Tried to set a(n) {self.subtype()} CDIVar"
                f" (packed via {self.packFormat()}) to {value}")
            raise

    def getSerializable(self):
        """Get a value in the corresponding Python type,
        or a string representing binary data."""
        if self.className == "int":
            return self.getInt()
        elif self.className == "float":
            return self.getFloat()
        elif self.className == "string":
            return self.getString()
        assert self.className in ("blob", "eventid", "action")
        assert self.data is not None, "CDIVar data not initialized"
        return base64.b64encode(self.data)

    def signedMsg(self) -> str:
        return "signed" if self.signed else "unsigned"

    def value(self):
        """Get the value as a directly comparable Python type"""
        if self.className == "int":
            return self.getInt()
        elif self.className == "float":
            return self.getFloat()
        elif self.className == "string":
            return self.getString()
        assert self.className in ("blob", "eventid", "action")
        assert self.data is not None, "CDIVar data not initialized"
        raise NotImplementedError(
            f"Converting binary {self.className} to a Python type")

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

    def _getFloat(self) -> float:
        assert self.className == "float"
        value = self.getFloat()
        assert value is not None
        return value

    def _getInt(self) -> int:
        assert self.className == "int"
        value = self.getInt()
        assert value is not None
        return value

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
