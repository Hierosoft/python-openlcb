
from enum import Enum
from typing import Union
# FDI = 0xFA
# Configuration = 0xFD
# All = 0xFE
# CDI = 0xFF  # ~~decodes~~ encoded (in header) as 0x03


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


class MemoryConfigurationHeader:
    """Manage data corresponding to bitfields in Memory Configuration.
    See OpenLCB "Memory Configuration" Standard

    Arguments:
        space (int): Space number (MemorySpaceIndex.*.Value,
            MemorySpace.*.value, or raw number including a custom
            space).
            - 0xFF to 0xFD are special spaces, and only the least
              significant 2 bits will be used in a datagram.
            - 0x00 to 0xFC represent standard memory spaces directly.
    """
    def __init__(self, space: int):
        # formerly Convert.serializeSpace
        # formerly spaceDecode, but it serializes a space for datagram byte2
        assert isinstance(space, int)
        spaceIndexValue = space & 0x03
        self.spaceIndex = \
            MemorySpaceIndex.fromNumber(
                spaceIndexValue)  # type: MemorySpaceIndex
        self.customSpace = None  # type: int|None
        if self.spaceIndex is MemorySpaceIndex.Custom:
            self.customSpace = space
        self.highBits = 0  # type: int

    @classmethod
    def fromMC2ndByte(cls, datagramByte1: int, space: Union[int, None] = None) -> 'MemoryConfigurationHeader':  # noqa: E501
        """Deserialize Memory Configuration byte 1.

        For serializing a space (such as packing a datagram header),
        use constructor instead.

        Args:
            datagramByte1 (int): byte[1] (2nd) of Memory Configuration Datagram
            space (int): Only applies for custom space (datagramByte)
        """
        if space is not None:
            assert isinstance(space, int)
            assert datagramByte1 & 0x03 == 0, \
                'custom space requires datagramByte1 with last 2 bits 00'
        else:
            # space is None
            assert datagramByte1 & 0x03 != 0, \
                'a standard space must be in last 2 bits datagramByte1'
            space = -1
        # formerly deserializeMC2ndByte
        result = cls(datagramByte1 & 0x03)
        if datagramByte1 & 0x03 == 0:
            # Default (-1) means not enough information
            #    (space not known, but is MemorySpaceIndex.Custom)
            result.customSpace = space
        result.highBits = datagramByte1 & 0xFC  # 0xFC = 0b11111100
        return result
