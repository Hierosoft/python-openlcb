'''
based on part of MemoryService.swift

Created by Bob Jacobsen on 6/1/22.

These parts moved to a separate class so callers of static methods don't
depend on MemoryService(DatagramService).

'''

from logging import getLogger
from typing import (
    List,  # in case list doesn't support `[` in this Python version
    Union,  # in case `|` doesn't support 'type' in this Python version
)

logger = getLogger(__name__)


class Convert:

    @staticmethod
    def arrayToInt(data: Union[bytes, bytearray, List[int]]) -> int:
        """Convert an array in MSB-first order to an integer

        Args:
            data (Union[bytes,bytearray,list[int]]): MSB-first order
                encoded 32-bit int

        Returns:
            int: The converted data as a number.
        """
        result = 0
        for index in range(0, len(data)):
            result = result << 8
            result = result | data[index]
        return result

    @staticmethod
    def toHex(data: Union[bytearray, bytes, List[int]], separator="_"):
        text = ""
        for i, num in enumerate(data):
            if not text:
                text = "0x"
            else:
                text += separator
            assert isinstance(num, int), \
                f"Expected byte/int array, got {type(data).__name__} at [{i}]"
            text += f"{num:#04x}"[2:]  # 4 for padded to 4 (2 excluding "0x")
        return text

    @staticmethod
    def arrayToUInt64(data):
        """Parse a MSB-first order 64-bit integer
        (Python auto-sizes int, so this is same as arrayToInt).
        """
        return Convert.arrayToInt(data)

    @staticmethod
    def arrayToString(data, length):
        """Decode utf-8 bytes to string
        up to the 1st zero byte or given length,
        whichever is fewer characters.

        Args:
            data (Union[bytearray, bytes]): A string encoded as bytes.
            length (int): The used length the data.

        Returns:
            str: Data decoded as text.
        """
        if not isinstance(data, bytearray):
            raise TypeError("Expected bytearray (formerly list[int]), got {}"
                            .format(type(data).__name__))
        zeroIndex = len(data)
        try:
            temp = data.index(0)
            zeroIndex = temp
        except KeyboardInterrupt:
            raise
        except:
            pass

        byteCount = min(zeroIndex, length)

        if byteCount == 0:
            return ""

        result = data[:byteCount].decode('utf-8')
        return result

    @staticmethod
    def intToArray(value, length):
        """Convert an integer into an array of given length

        Args:
            value (int): any value
            length (int): Byte count (1, 2, 4, or 8).

        Returns:
            bytearray: The value encoded in big-endian format.
        """
        if value >= (1 << (length * 8)):  # TODO: ? also exclude value < 0 ?
            raise ValueError("Value {} cannot fit in {} bytes."
                             .format(value, length))
        if length == 1:
            return bytearray([
                (value & 0xff)
            ])
        if length == 2:
            return bytearray([
                ((value >> 8) & 0xff), (value & 0xff)
            ])
        if length == 4:
            return bytearray([
                ((value >> 24) & 0xff), ((value >> 16) & 0xff),
                ((value >> 8) & 0xff),  (value & 0xff)
            ])
        if length == 8:
            return bytearray([
                ((value >> 56) & 0xff), ((value >> 48) & 0xff),
                ((value >> 40) & 0xff), ((value >> 32) & 0xff),
                ((value >> 24) & 0xff), ((value >> 16) & 0xff),
                ((value >> 8) & 0xff), (value & 0xff)
            ])
        logger.error("integer length {} is not implemented.".format(length))
        return bytearray()

    @staticmethod
    def uInt64ToArray(value, length):
        '''Convert a 64-bit integer into an array of given length
        (Python auto-sizes int, so this is same as intToArray)
        '''
        return Convert.intToArray(value, length)

    @staticmethod
    def stringToArray(value, length):
        '''Converts a string to an array of given length
        padding with 0 bytes as needed
        '''
        strToUInt8 = value.encode('utf-8')
        byteCount = min(length, len(strToUInt8))
        # convert to bytearray since bytes is immutable:
        contentPart = bytearray(strToUInt8[:byteCount])
        if len(contentPart) >= length:
            if len(contentPart) > length:
                logger.warning(
                    "MemoryService stringToArray: len(value)=={}"
                    " exceeds length {}".format(len(value), length))
                # TODO: Truncate (or is any length ok for the caller)?
            return contentPart
        # list[int] is compatible bytearray extend but not `+` so cast
        #   to bytearray after getting list[int] of remaining length:
        padding = bytearray([0] * (length-len(contentPart)))
        return contentPart + padding

    @staticmethod
    def getBeforeNull(data: Union[bytes, bytearray], start):
        null_idx = -1
        for i in range(start, len(data)):
            assert isinstance(data[i], int)
            if data[i] == 0:
                null_idx = i
                break
        if null_idx > -1:
            return data[start:null_idx]
        return data[start:]
