from enum import Enum

from openlcb.memoryspaceindex import MemorySpaceIndex


class MemorySpace(Enum):
    """The memory space to read.
    In practice, XMLDataProcessor (or a non-XML parser if necessary)
    uses this to track what data type and format is to be assumed in a
    received Message. It is assumed to have the same space as the
    request (MemoryReadMemo).
    - A datagram's `space` attribute's type should be `int` not
      MemorySpace, because CDI specifies variables' space arbitrarily.

    Attributes:
        Uninitialized: No data (memory read request response) is expected.
        CDI: The data expected from the memory read is CDI XML.
        FDI: The data expected from the memory read is FDI XML.
        All: All memory of the device, where all is defined by its designer
            (See OpenLCB Memory Configuration Standard 4.2).
        Configuration: A writeable basic configuration space, with
            the structure of the 32-bit space defined by the designer
            (See OpenLCB Memory Configuration Standard 4.2).
    """
    Uninitialized = -1
    FDI = 0xFA
    Configuration = 0xFD
    All = 0xFE
    CDI = 0xFF  # decodes to 0x03

    @classmethod
    def fromNumber(cls, num: int):
        """Return the MemorySpace member with the given numeric value,
        or None if no match is found.
        """
        assert isinstance(num, int)
        for member in cls:
            if member.value == num:
                return member
        return None

    @classmethod
    def fromIndex(cls, msi: MemorySpaceIndex):
        """Return the MemorySpace member with the given numeric value,
        or None if no match is found.
        """
        assert isinstance(msi, MemorySpaceIndex)
        if msi is MemorySpaceIndex.Custom:
            return None
        elif msi is MemorySpaceIndex.Configuration:
            return cls.Configuration
        elif msi is MemorySpaceIndex.All:
            return cls.All
        elif msi is MemorySpaceIndex.CDI:
            return cls.CDI
        return None
