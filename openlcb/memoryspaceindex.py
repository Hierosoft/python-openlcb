

from enum import Enum


class MemorySpaceIndex(Enum):
    Uninitialized = -1
    Custom = 0
    Configuration = 1  # 0xFD & 0x03 == 1
    All = 2  # 0xFE & 0x03 == 2
    CDI = 3  # 0xFF & 0x03 == 3

    @classmethod
    def fromNumber(cls, num: int):
        """Return the MemorySpace member with the given numeric value,
        or None if no match is found.
        """
        assert isinstance(num, int)
        for member in cls:
            if member.value == num:
                return member
        return cls.Custom
