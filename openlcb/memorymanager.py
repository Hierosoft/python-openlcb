from logging import getLogger
import struct
from typing import Callable, Union

from openlcb.cdivar import SUBTYPE_FORMATS, CDIVar
from openlcb.memoryspace import MemorySpace

logger = getLogger(__name__)


class Segment:
    """A memory segment that is contiguous or behaves as such.
    """
    def __init__(self, size=0, readOnly=False):
        assert isinstance(size, int)
        assert size >= 0
        assert isinstance(readOnly, bool)
        self._description = None
        self._first = None
        self._last = None
        if size == 0:
            self._data = bytearray()
        else:
            self._data = bytearray(b"\0"*size)
        self._readOnly = readOnly

    def getFirst(self):
        if self._first is None:
            return 0
        assert isinstance(self._first, int)
        return self._first

    def getLast(self):
        if self._last is None:
            return self.getFirst() + len(self._data) - 1
            # ^ -1 since inclusive
        assert isinstance(self._last, int)
        return self._last

    def getLength(self):
        return self.getLast() - self.getFirst() + 1

    def getSlice(self, address: int, size: int, force=False):
        end = address + size
        if address >= len(self._data):
            if force:
                data = bytearray(size*b"\0")
                self.setSlice(address, data, force=force)
                return data
            else:
                raise IndexError(
                    f"Tried to get address {address}"
                    f"in {self.getLength()}-long space")
        elif end > len(self._data):
            slack = end - len(self._data)
            offset = size - slack
            if force:
                self.setSlice(address + offset, slack*b"\0")
            else:
                raise IndexError(
                    f"Tried to get address {address}"
                    f"in {self.getLength()}-long space")
        return self._data[address:end]

    def getDescription(self) -> Union[str, None]:
        return self._description

    def setDescription(self, description: str):
        assert isinstance(description, str)
        self._description = description

    def isReadOnly(self) -> bool:
        return self._readOnly

    def markReadOnly(self, readOnly: bool):
        assert isinstance(readOnly, bool)
        self._readOnly = readOnly

    def extend(self, data):
        self._data += data

    def setSlice(self, address: int, data: Union[bytearray, bytes],
                 size: Union[int, None] = None, force=True):
        assert isinstance(data, (bytearray, bytes))
        assert isinstance(address, int)
        assert address >= 0
        if size is None:
            size = len(data)
        else:
            assert size <= len(data)
        end = address + size
        newRegionLen = end - len(self._data)
        if newRegionLen > 0:
            if force:
                logger.warning(
                    f"Extending LocalNode data from {len(self._data)}"
                    f" byte(s) to {end} byte(s).")
                self.extend(b'\0' * newRegionLen)
            else:
                raise IndexError(
                    f"Tried to set address {address}"
                    f"in {self.getLength()}-long space")
        assert end - address == len(data)
        if size < len(data):
            self._data[address:end] = data[:size]
        else:
            self._data[address:end] = data

    def size(self) -> int:
        return len(self._data)


class MemoryManager:
    """A collection of memory segments.
    Attributes:
        watchVars (Dict[int, Dict[int, CDIVar]]): Variables that will be
            used as the argument to callbacks, as well as set when
            memory is set, at the address corresponding to the 2nd
            tier's integer key. The 1st tier of the dict is keyed by a
            space int.
            - If not present, and setSlice is used (without the optional
              callbackVar) no registered callbacks will be called (Not
              enough information).

    """

    def __init__(self):
        self._segments = {}  # type: dict[int, Segment]
        self._writeListeners = []
        self.watchVars = {}  # type: dict[int, dict[int, CDIVar]]

    def set(self, var: CDIVar):
        assert issubclass(type(var), CDIVar)
        assert var.space is not None
        assert var.address is not None
        data = var.getData()
        assert data is not None
        watchVar = self.getWatchVar(var.space, var.address)
        if watchVar is not None:
            var = watchVar
            assert var.space is not None
            assert var.address is not None
        self.setSlice(var.space, var.address, data, size=var.size,
                      callbackVar=var)

    def getFirst(self, space: Union[MemorySpace, int]):
        """Get first address"""
        if isinstance(space, MemorySpace):
            space = space.value
        segment = self._segments.get(space)
        if segment is None:
            return None
        return segment.getFirst()

    def markReadOnly(self, space: Union[MemorySpace, int], readOnly):
        if isinstance(space, MemorySpace):
            space = space.value
        segment = self._segments.get(space)
        if segment is None:
            return
        return segment.markReadOnly(readOnly)

    def isReadOnly(self, space: Union[MemorySpace, int]):
        if isinstance(space, MemorySpace):
            space = space.value

        segment = self._segments.get(space)
        if segment is None:
            return True  # True since can't write if not present
        return segment.isReadOnly()

    def getDescription(self, space):
        if isinstance(space, MemorySpace):
            space = space.value
        segment = self._segments.get(space)
        if segment is None:
            return None
        return segment.getDescription()

    def setDescription(self, space, description: str):
        if isinstance(space, MemorySpace):
            space = space.value
        assert isinstance(description, str)
        segment = self._segments.get(space)
        if segment is None:
            return
        segment.setDescription(description)

    def getLength(self, space: Union[MemorySpace, int]):
        """Get size of space"""
        if isinstance(space, MemorySpace):
            space = space.value
        if space not in self._segments:
            return None
        return self._segments[space].getLength()

    def getLast(self, space: Union[MemorySpace, int]):
        """Get last address
        (may differ from length-1 on actual hardware)
        """
        if isinstance(space, MemorySpace):
            space = space.value
        segment = self._segments.get(space)
        if segment is None:
            return None
        return segment.getLast()

    def getSegment(self, space: Union[MemorySpace, int]) -> Union[Segment, None]:  # noqa: E501
        """Get last address
        (may differ from length-1 on actual hardware)
        """
        if isinstance(space, MemorySpace):
            space = space.value
        return self._segments.get(space)

    def get(self, var: CDIVar) -> CDIVar:
        """Modify var in place.

        Returns:
            CDIVar: Same var instance (returned by reference) modified.
        """
        assert issubclass(type(var), CDIVar)
        assert var.space is not None
        assert var.address
        assert var.size is not None
        data = self.getSlice(var.space, var.address, var.size)
        assert data is not None
        var.setData(data)
        return var

    def setSlice(self, space: Union[MemorySpace, int], address: int,
                 data: Union[bytes, bytearray], size=None,
                 callbackVar: Union[CDIVar, None] = None) -> Segment:
        """Set address in virtual memory space to data.
        fireWriteListeners can only be called if
        callbackVar is known, otherwise type information
        is not available at this level.
        """
        assert isinstance(data, (bytearray, bytes))
        if isinstance(space, MemorySpace):
            space = space.value
        assert isinstance(space, int)
        assert isinstance(address, int)
        assert address >= 0
        if size is None:
            size = len(data)
        else:
            assert size <= len(data)
        segment = self._segments.get(space)
        if segment is None:
            segment = Segment()
            self._segments[space] = segment
        segment.setSlice(address, data, size=size)
        if callbackVar is None:
            callbackVar = self.getWatchVar(space, address)
        if callbackVar is not None:
            callbackVar.setData(data)
            self.fireWriteListeners(callbackVar)
        return segment

    def getSlice(self, space: Union[MemorySpace, int], address: int,
                 size: int, force=False) -> bytearray:
        if isinstance(space, MemorySpace):
            space = space.value
        assert isinstance(space, int)
        assert isinstance(address, int)
        assert isinstance(size, int)
        segment = self._segments.get(space)
        if segment is None:
            if force:
                segment = Segment(size=address+size)
                segment.setSlice(address, b"\0"*size, force=True)
                self._segments[space] = segment
            else:
                raise KeyError(f"Space {hex(space)} does not exist.")
        return segment.getSlice(address, size, force=force)

    def setInt(self, space: Union[MemorySpace, int], address: int,
               value: int, size: int, signed: bool):
        if isinstance(space, MemorySpace):
            space = space.value
        assert isinstance(space, int)
        assert isinstance(address, int)
        assert isinstance(size, int)
        assert isinstance(signed, bool)
        assert size in (1, 2, 4, 8)
        typeStr = f"int{size*8}"
        dataFormat = SUBTYPE_FORMATS[typeStr]
        data = struct.pack(dataFormat, value)
        assert len(data) == size, \
            f"Expected {size} byte(s) for {typeStr}, got {len(data)}"
        var = self.getWatchVar(space, address)
        if var is None:
            var = CDIVar("int", _size=size, _no_min=True, _no_max=True,
                         space=space, address=address)
        result = self.setSlice(space, address, data, callbackVar=var)
        if self._writeListeners:
            self.fireWriteListeners(var)
        return result

    def getInt(self, space: Union[MemorySpace, int], address: int,
               size: int, signed: bool) -> int:
        if isinstance(space, MemorySpace):
            space = space.value
        assert isinstance(space, int)
        assert isinstance(address, int)
        assert isinstance(size, int)
        assert isinstance(signed, bool)
        data = self.getSlice(space, address, size)
        assert size in (1, 2, 4, 8)
        typeStr = f"int{size*8}"
        if not signed:
            typeStr = "u" + typeStr
        dataFormat = SUBTYPE_FORMATS[typeStr]
        values = struct.unpack(dataFormat, data)
        assert len(values) == 1, f"Expected 1 {typeStr}, got {len(values)}"
        assert isinstance(values[0], int)
        return values[0]

    def setFloat(self, space: Union[MemorySpace, int], address: int,
                 value: float, size: int):
        if isinstance(space, MemorySpace):
            space = space.value
        assert isinstance(space, int)
        assert isinstance(address, int)
        assert isinstance(size, int)
        assert size in (2, 4, 8)
        typeStr = f"float{size*8}"
        dataFormat = SUBTYPE_FORMATS[typeStr]
        data = struct.pack(dataFormat, value)
        assert len(data) == size, \
            f"Expected {size} byte(s) for {typeStr}, got {len(data)}"
        var = self.getWatchVar(space, address)
        if var is None:
            var = CDIVar("float", _size=size, _no_min=True, _no_max=True,
                         space=space, address=address)
        result = self.setSlice(space, address, data, callbackVar=var)
        if self._writeListeners:
            self.fireWriteListeners(var)
        return result

    def getFloat(self, space: Union[MemorySpace, int], address: int,
                 size: int) -> float:
        if isinstance(space, MemorySpace):
            space = space.value
        assert isinstance(space, int)
        assert isinstance(address, int)
        assert isinstance(size, int)
        data = self.getSlice(space, address, size)
        assert size in (2, 4, 8)
        typeStr = f"float{size*8}"
        dataFormat = SUBTYPE_FORMATS[typeStr]
        values = struct.unpack(dataFormat, data)
        assert len(values) == 1, f"Expected 1 {typeStr}, got {len(values)}"
        assert isinstance(values[0], float)
        return values[0]

    def registerWriteListener(self, callback: Callable[[CDIVar], None]):
        """Register a function to call when a value is written.
        NOTE: You must also call registerWatchVar or low-level
        (setSlice) calls will not trigger a callback due to not enough
        information (callback takes a CDIVar).
        """
        self._writeListeners.append(callback)

    def registerWatchVar(self, var: CDIVar):
        """Register a CDIVar to track writes.

        Arguments:
            var (CDIVar): Must have var.space
                and var.address in order to be tracked. This var's value
                will be edited remotely, and will allow write listeners
                to fire even when setting memory of a non-number or
                unspecified type (using setSlice).
        Raises:
            AssertionError: space or address is None.
        """
        # a.k.a. setWatchVar
        assert var.space is not None, \
            'cdivar.space is required in order to listen for change'
        if isinstance(var.space, MemorySpace):
            var.space = var.space.value
        assert isinstance(var.space, int)
        assert var.address is not None, \
            'cdivar.address is required in order to listen for change'
        assert isinstance(var.address, int)
        if var.space not in self.watchVars:
            self.watchVars[var.space] = {}
        if var.address in self.watchVars[var.space]:
            raise KeyError(
                f"Address {var.address} of space {var.space}"
                " is already registered.")
        self.watchVars[var.space][var.address] = var

    def getWatchVar(self, space: Union[MemorySpace, int], address: int,
                    default: Union[CDIVar, None] = None):
        assert space is not None
        assert address is not None
        if isinstance(space, MemorySpace):
            space = space.value
        assert isinstance(space, int)
        assert isinstance(address, int)
        if default is not None:
            assert issubclass(type(default), CDIVar)
        spaceVars = self.watchVars.get(space)
        if spaceVars is None:
            return None
        var = spaceVars.get(address, default)
        if var is not None:
            # Fix space & address so fireWriteListeners works correctly
            if var.space is None:
                logger.warning(
                    f"Setting var.space={space} using its location")
                var.space = space
            elif var.space != space:
                logger.warning(
                    f"Setting incorrect var.space {var.space}"
                    f" to {space} using its location")
                var.space = space
            if var.address is None:
                logger.warning(
                    f"Setting var.address={address} using its location")
                var.address = address
            elif var.address != address:
                logger.warning(
                    f"Setting incorrect var.address {var.address}"
                    f" to {address} using its location")
                var.address = address
        return var

    def fireWriteListeners(self, var: CDIVar):
        for writeListener in self._writeListeners:
            writeListener(var)
