
from enum import Enum
from typing import Union

from openlcb.memoryspaceindex import MemorySpaceIndex
# FDI = 0xFA
# Configuration = 0xFD
# All = 0xFE
# CDI = 0xFF  # ~~decodes~~ encoded (in header) as 0x03


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
                'a standard space index must be in last 2 bits datagramByte1'
            space = -1
        # NOTE: Third option is that space isn't known yet
        #   (must be set later, if spaceIsCustom())
        # formerly deserializeMC2ndByte
        result = cls(datagramByte1 & 0x03)
        if datagramByte1 & 0x03 == 0:
            # Default (-1) means not enough information
            #    (space not known, but is MemorySpaceIndex.Custom)
            result.customSpace = space
        result.highBits = datagramByte1 & 0xFC  # 0xFC = 0b11111100
        return result

    def spaceIsCustom(self):
        """Is MemorySpaceIndex.Custom?
        Detected as True if 0 was in last 2 bits of datagramByte1
        (2nd byte of datagram bitwise-and 6-high-bit mask),
        so only use fromMC2ndByte (or MemorySpaceIndex.fromNumber) if
        `isinstance(TWO_BIT_PARAMS[datagramByte1 & McOpMasks.Default], list)`
        (list is used as a convention in TWO_BIT_PARAMS values to
        indicate a meaningful index in last 2 bits).
        """
        return self.spaceIndex is MemorySpaceIndex.Custom
