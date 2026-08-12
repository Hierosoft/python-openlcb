

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
        Args:
            num (int): Typically datagramByte1 & McOpMasks.Default
                (2nd byte of datagram bitwise-and 6-high-bit mask), so
                only use this method if if
                `isinstance(TWO_BIT_PARAMS[datagramByte1 &
                McOpMasks.Default], list)`
                (list is used as a convention in TWO_BIT_PARAMS values
                to indicate a meaningful index in last 2 bits).
        """
        assert isinstance(num, int)
        for member in cls:
            if member.value == num:
                return member
        return cls.Custom
