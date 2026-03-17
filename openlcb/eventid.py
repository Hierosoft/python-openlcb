'''
based on EventID.swift

Created by Bob Jacobsen on 6/1/22.


'''


from openlcb import emit_cast


class EventID:
    """Represents an 8-byte event ID.
    Provides conversion to and from Ints and Strings in standard form.

    Attributes:
        value (int): 8-byte event ID (ints are scalable in Python, but
            it represents a UInt64). Formerly eventId (renamed for
            clarity since it is an int not an EventID instance).
    """
    def __str__(self):
        '''Display in standard format'''
        c = self.toArray()
        return ("{:02X}.{:02X}.{:02X}.{:02X}.{:02X}.{:02X}.{:02X}.{:02X}"
                "".format(c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[7]))

    # Convert an integer, list, EventID or string to an EventID
    def __init__(self, data):
        if isinstance(data, int):  # create from an integer value
            self.value = data
        elif isinstance(data, str):  # need to allow for 1 digit numbers
            parts = data.split(".")
            result = 0
            for part in parts:
                result = result*0x100+int(part, 16)
            self.value = result
        elif isinstance(data, EventID):
            self.value = data.value
        elif isinstance(data, bytearray):
            self.value = 0
            if (len(data) > 0):
                self.value |= (data[0] & 0xFF) << 56
            if (len(data) > 1):
                self.value |= (data[1] & 0xFF) << 48
            if (len(data) > 2):
                self.value |= (data[2] & 0xFF) << 40
            if (len(data) > 3):
                self.value |= (data[3] & 0xFF) << 32
            if (len(data) > 4):
                self.value |= (data[4] & 0xFF) << 24
            if (len(data) > 5):
                self.value |= (data[5] & 0xFF) << 16
            if (len(data) > 6):
                self.value |= (data[6] & 0xFF) << 8
            if (len(data) > 7):
                self.value |= (data[7] & 0xFF)
        # elif isinstance(data, list):
        else:
            raise TypeError("invalid data type to EventID constructor: {}"
                            .format(emit_cast(data)))

    def toArray(self):
        return bytearray([
            (self.value >> 56) & 0xFF,
            (self.value >> 48) & 0xFF,
            (self.value >> 40) & 0xFF,
            (self.value >> 32) & 0xFF,
            (self.value >> 24) & 0xFF,
            (self.value >> 16) & 0xFF,
            (self.value >> 8) & 0xFF,
            (self.value) & 0xFF
        ])

    def __eq__(self, other):
        if self.value != other.value:
            return False
        return True

    def __hash__(self):
        return hash(self.value)
