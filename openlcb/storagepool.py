from logging import getLogger
import struct
from typing import Union

from openlcb.cdivar import SUBTYPE_FORMATS, CDIVar
from openlcb.memoryspace import MemorySpace

logger = getLogger(__name__)


class StorageSpace:
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
                self.setData(address, data, force=force)
                return data
            else:
                raise IndexError(
                    f"Tried to get address {address}"
                    f"in {self.getLength()}-long space")
        elif end > len(self._data):
            slack = end - len(self._data)
            offset = size - slack
            if force:
                self.setData(address + offset, slack*b"\0")
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

    def setData(self, address: int, data: Union[bytearray, bytes],
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


class StoragePool:
    def __init__(self):
        self._spaces = {}  # type: dict[int, StorageSpace]

    def set(self, var: CDIVar):
        assert isinstance(var, CDIVar)
        assert var.space is not None
        assert var.address
        data = var.getData()
        assert data is not None
        self.setSlice(var.space, var.address, data, size=var.size)

    def getFirst(self, space: Union[MemorySpace, int]):
        """Get first address"""
        if isinstance(space, MemorySpace):
            space = space.value
        storage = self._spaces.get(space)
        if storage is None:
            return None
        return storage.getFirst()

    def markReadOnly(self, space: Union[MemorySpace, int], readOnly):
        if isinstance(space, MemorySpace):
            space = space.value
        storage = self._spaces.get(space)
        if storage is None:
            return
        return storage.markReadOnly(readOnly)

    def isReadOnly(self, space: Union[MemorySpace, int]):
        if isinstance(space, MemorySpace):
            space = space.value

        storage = self._spaces.get(space)
        if storage is None:
            return True  # True since can't write if not present
        return storage.isReadOnly()

    def getDescription(self, space):
        if isinstance(space, MemorySpace):
            space = space.value
        storage = self._spaces.get(space)
        if storage is None:
            return None
        return storage.getDescription()

    def setDescription(self, space, description: str):
        if isinstance(space, MemorySpace):
            space = space.value
        assert isinstance(description, str)
        storage = self._spaces.get(space)
        if storage is None:
            return
        storage.setDescription(description)

    def getLength(self, space: Union[MemorySpace, int]):
        """Get size of space"""
        if isinstance(space, MemorySpace):
            space = space.value
        if space not in self._spaces:
            return None
        return self._spaces[space].getLength()

    def getLast(self, space: Union[MemorySpace, int]):
        """Get last address
        (may differ from length-1 on actual hardware)
        """
        if isinstance(space, MemorySpace):
            space = space.value
        storage = self._spaces.get(space)
        if storage is None:
            return None
        return storage.getLast()

    def getStorage(self, space: Union[MemorySpace, int]) -> Union[StorageSpace, None]:  # noqa: E501
        """Get last address
        (may differ from length-1 on actual hardware)
        """
        if isinstance(space, MemorySpace):
            space = space.value
        return self._spaces.get(space)

    def get(self, var: CDIVar) -> CDIVar:
        """Modify var in place.

        Returns:
            CDIVar: Same var instance (returned by reference) modified.
        """
        assert isinstance(var, CDIVar)
        assert var.space is not None
        assert var.address
        assert var.size is not None
        data = self.getSlice(var.space, var.address, var.size)
        assert data is not None
        var.setData(data)
        return var

    def setSlice(self, space: Union[MemorySpace, int], address: int,
                 data: Union[bytes, bytearray], size=None):
        """Set address in virtual memory space to data"""
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
        storage = self._spaces.get(space)
        if storage is None:
            storage = StorageSpace()
            self._spaces[space] = storage
        storage.setData(address, data, size=size)

    def getSlice(self, space: Union[MemorySpace, int], address: int,
                 size: int, force=False) -> bytearray:
        if isinstance(space, MemorySpace):
            space = space.value
        assert isinstance(space, int)
        assert isinstance(address, int)
        assert isinstance(size, int)
        storage = self._spaces.get(space)
        if storage is None:
            if force:
                storage = StorageSpace(size=address+size)
                storage.setData(address, b"\0"*size, force=True)
                self._spaces[space] = storage
            else:
                raise KeyError(f"Space {hex(space)} does not exist.")
        return storage.getSlice(address, size, force=force)

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
        return self.setSlice(space, address, data)

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
        return self.setSlice(space, address, data)

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
