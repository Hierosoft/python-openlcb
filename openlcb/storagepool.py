from logging import getLogger

from openlcb.memoryspace import MemorySpace

logger = getLogger(__name__)


class StoragePool:
    def __init__(self):
        self.spaces = {}  # type: dict[int, bytearray]

    def set(self, space, address, data):
        """Set address in virtual memory space to data"""
        assert isinstance(data, (bytearray, bytes))
        if isinstance(space, MemorySpace):
            space = space.value
        assert isinstance(space, int)
        assert isinstance(address, int)
        assert address >= 0
        size = len(data)
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
        self.spaces[space][address:end] = data

    def get(self, space, address, size, force=False) -> bytearray:
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
            self.set(space, address, size*b"\0")
        elif end > len(self.spaces[space]):
            slack = end - len(self.spaces[space])
            offset = size - slack
            self.set(space, address + offset, slack*b"\0")
        return self.spaces[space][address:end]
