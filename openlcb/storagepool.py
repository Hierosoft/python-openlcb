from logging import getLogger
import struct
from typing import Union

from openlcb.cdivar import SUBTYPE_FORMATS, CDIVar
from openlcb.memoryspace import MemorySpace

logger = getLogger(__name__)


class StoragePool:
    def __init__(self):
        self.spaces = {}  # type: dict[int, bytearray]

    def set(self, var: CDIVar):
        assert isinstance(var, CDIVar)
        assert var.space is not None
        assert var.address
        data = var.getData()
        assert data is not None
        self.setData(var.space, var.address, data, size=var.size)

    def get(self, var: CDIVar) -> CDIVar:
        """Modify var in place.

        Returns:
            CDIVar: Same var instance (returned by reference) modified.
        """
        assert isinstance(var, CDIVar)
        assert var.space is not None
        assert var.address
        assert var.size is not None
        data = self.getData(var.space, var.address, var.size)
        assert data is not None
        var.setData(data)
        return var

    def setData(self, space: Union[MemorySpace, int], address: int,
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
        end = address + size

        if space not in self.spaces:
            self.spaces[space] = bytearray()
        else:
            assert isinstance(self.spaces[space], bytearray)

        newRegionLen = end - len(self.spaces[space])
        if newRegionLen > 0:
            logger.warning(
                f"Extending LocalNode data from {len(self.spaces[space])}"
                f" byte(s) to {end} byte(s).")
            self.spaces[space] += b'\0' * newRegionLen
        assert end - address == len(data)
        if size < len(data):
            self.spaces[space][address:end] = data[:size]
        else:
            self.spaces[space][address:end] = data

    def getData(self, space: Union[MemorySpace, int], address: int,
                size: int, force=False) -> bytearray:
        if isinstance(space, MemorySpace):
            space = space.value
        assert isinstance(space, int)
        assert isinstance(address, int)
        assert isinstance(size, int)
        if space not in self.spaces:
            if force:
                self.spaces[space] = bytearray()
            else:
                raise KeyError(f"Space {hex(space)} does not exist.")

        end = address + size
        if address >= len(self.spaces[space]):
            self.setData(space, address, size*b"\0")
        elif end > len(self.spaces[space]):
            slack = end - len(self.spaces[space])
            offset = size - slack
            self.setData(space, address + offset, slack*b"\0")
        return self.spaces[space][address:end]

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
        return self.setData(space, address, data)

    def getInt(self, space: Union[MemorySpace, int], address: int,
               size: int, signed: bool) -> int:
        if isinstance(space, MemorySpace):
            space = space.value
        assert isinstance(space, int)
        assert isinstance(address, int)
        assert isinstance(size, int)
        assert isinstance(signed, bool)
        data = self.getData(space, address, size)
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
        return self.setData(space, address, data)

    def getFloat(self, space: Union[MemorySpace, int], address: int,
                 size: int) -> float:
        if isinstance(space, MemorySpace):
            space = space.value
        assert isinstance(space, int)
        assert isinstance(address, int)
        assert isinstance(size, int)
        data = self.getData(space, address, size)
        assert size in (2, 4, 8)
        typeStr = f"float{size*8}"
        dataFormat = SUBTYPE_FORMATS[typeStr]
        values = struct.unpack(dataFormat, data)
        assert len(values) == 1, f"Expected 1 {typeStr}, got {len(values)}"
        assert isinstance(values[0], float)
        return values[0]
