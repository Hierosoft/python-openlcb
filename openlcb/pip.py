'''
based on PIP.swift
Created by Bob Jacobsen on 6/1/22.

Defines the various protocol bits as a enum, and
provides a routine for converting a numeric value to a set of enum constants.
'''

from enum import Enum
from typing import (
    Iterable,
    List,
    Set,  # in case list doesn't support `[` in this Python version
    Union,  # in case `|` doesn't support 'type' in this Python version
)


class PIP(Enum):
    """Coded as a 32-bit values
    instead of the 24-bit values in the standard to give expansion room.
    """
    SIMPLE_PROTOCOL                        = 0x80_00_00_00
    DATAGRAM_PROTOCOL                      = 0x40_00_00_00
    STREAM_PROTOCOL                        = 0x20_00_00_00
    MEMORY_CONFIGURATION_PROTOCOL          = 0x10_00_00_00
    RESERVATION_PROTOCOL                   = 0x08_00_00_00
    EVENT_EXCHANGE_PROTOCOL                = 0x04_00_00_00
    IDENTIFICATION_PROTOCOL                = 0x02_00_00_00
    TEACH_LEARN_PROTOCOL                   = 0x01_00_00_00
    REMOTE_BUTTON_PROTOCOL                 = 0x00_80_00_00
    ADCDI_PROTOCOL                         = 0x00_40_00_00
    DISPLAY_PROTOCOL                       = 0x00_20_00_00
    SIMPLE_NODE_IDENTIFICATION_PROTOCOL    = 0x00_10_00_00
    CONFIGURATION_DESCRIPTION_INFORMATION  = 0x00_08_00_00
    TRAIN_CONTROL_PROTOCOL                 = 0x00_04_00_00
    FUNCTION_DESCRIPTION_INFORMATION       = 0x00_02_00_00
    DCC_COMMAND_STATION_PROTOCOL           = 0x00_01_00_00
    SIMPLE_TRAIN_NODE_INFO_PROTOCOL        = 0x00_00_80_00
    FUNCTION_CONFIGURATION                 = 0x00_00_40_00
    FIRMWARE_UPGRADE_PROTOCOL              = 0x00_00_20_00
    FIRMWARE_ACTIVE                        = 0x00_00_10_00

    # get a list of all enum entries
    def list() -> List:
        return list(map(lambda c: c, PIP))

    def contentsNamesFromInt(bitmask: int) -> List[str]:
        """Convert protocol bits to strings.

        Args:
            contents (int): 0 or more PIP values
                (protocol bits) combined (as a single bitmask).

        Returns:
            list[str]: Names found in an int value.
        """
        retval = []
        for pip in PIP.list():
            if (pip.value & bitmask == pip.value):
                val = pip.name.replace("_", " ").title()
                if val.startswith("Adcdi"):
                    val = "ADCDI Protocol"  # Handle special case
                retval.append(val)
        return retval

    def contentsNamesFromList(pipList: Iterable) -> List[str]:
        """Convert a list of PIP values to strings.

        Args:
            contents (Iterable[PIP]): 0 or more PIP enums.
                May be a list or any other collection.

        Returns:
            list[str]: Names of PIP enums in contents.
        """
        retval = []
        for pip in pipList:
            val = pip.name.replace("_", " ").title()
            if val.startswith("Adcdi") :
                val = "ADCDI Protocol"  # Handle special case
            retval.append(val)
        return retval

    def setContentsFromInt(bitmask: int) -> Set:
        """Get a set of contents from a single numeric bitmask

        Args:
            bitmask (int): A single number that is the sum of any number of
                protocol bits.

        Returns:
            set(PIP): The set of protocol bits (bitmasks where 1 bit is on in
                each) derived from the bitmask.
        """
        retVal = []
        for pip in PIP.list():  # for each PIP
            if (pip.value & bitmask != 0):
                retVal.append(pip)
        return set(retVal)

    def setContentsFromList(
            values: Union[bytearray, bytes, Iterable[int]]) -> Set:
        """set contents from a list of numeric inputs

        Args:
            values (Union[bytes,list[int]]): a list of 1-byte values

        Returns:
            set (PIP): The set of protocol bits derived from the raw data.
        """
        bitmask = 0
        if (len(values) > 0):
            bitmask |= ((values[0]) << 24)
        if (len(values) > 1):
            bitmask |= ((values[1]) << 16)
        if (len(values) > 2):
            bitmask |= ((values[2]) << 8)
        if (len(values) > 3):
            bitmask |= ((values[3]))
        return PIP.setContentsFromInt(bitmask)
