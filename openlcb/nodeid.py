from openlcb import emit_cast
from openlcb.conventions import generate_node_id_str


class NodeID:
    """A 6-byte (48-bit) Node ID.
    The constructor is manually overloaded as follows:
    - NodeID_value (int): If int.
    - NodeID_value (str): If str. Six dot-separated hex pairs.
    - NodeID_value (NodeID): If NodeID. data.nodeID is used in this case.
    - NodeID_value (bytearray): If bytearray (formerly list[int]). Six ints.

    Args:
        data (Union[int,str,NodeID,list[int]]): Node ID in int, dotted
            hex string, NodeID, or list[int] form.

    Attributes:
        value (int): The node id in int form (uses 48 bits, so Python
            will allocate 64-bit or larger int). Formerly nodeID
            (renamed for clarity especially when using it in other code
            since it is an int not a NodeID)
    """
    def __str__(self):
        '''Display in standard format'''
        c = self.toArray()
        return ("{:02X}.{:02X}.{:02X}.{:02X}.{:02X}.{:02X}"
                "".format(c[0], c[1], c[2], c[3], c[4], c[5]))

    def __repr__(self):
        return self.__str__()

    def __init__(self, data):
        # For args see class docstring.
        if isinstance(data, int):  # create from an integer value
            self.value = data
        elif isinstance(data, str):
            parts = data.split(".")
            result = 0
            if len(parts) != 6:
                raise ValueError(
                    "6 dot-separated hex digits/pairs required if arg is str,"
                    " but got {}".format(emit_cast(data)))
            for part in parts:
                result = result*0x100+int(part, 16)
            self.value = result
        elif isinstance(data, NodeID):
            self.value = data.value
        elif isinstance(data, bytearray):
            self.value = 0
            if (len(data) > 0):
                self.value |= (data[0] & 0xFF) << 40
            if (len(data) > 1):
                self.value |= (data[1] & 0xFF) << 32
            if (len(data) > 2):
                self.value |= (data[2] & 0xFF) << 24
            if (len(data) > 3):
                self.value |= (data[3] & 0xFF) << 16
            if (len(data) > 4):
                self.value |= (data[4] & 0xFF) << 8
            if (len(data) > 5):
                self.value |= (data[5] & 0xFF)
        elif isinstance(data, list):
            print("invalid data type to nodeid constructor."
                  " Expected bytearray (formerly list[int])"
                  " unless int, str nor NodeID", data)
        else:
            print("invalid data type to nodeid constructor", data)

    def toArray(self) -> bytearray:
        return bytearray([
            (self.value >> 40) & 0xFF,
            (self.value >> 32) & 0xFF,
            (self.value >> 24) & 0xFF,
            (self.value >> 16) & 0xFF,
            (self.value >> 8) & 0xFF,
            (self.value) & 0xFF
        ])

    def __eq__(self, other):
        if other is None:
            return False

        if self.value != other.value:
            return False
        return True

    def __hash__(self):
        return hash(self.value)


def generate_node_id(id_range_prefix):
    """Generate a unique NodeID for the session to ensure each
    instance (even of python-openlcb on same device) or
    locally-generated virtual node is unique.

    Args:
        id_range_prefix (str): NodeID prefix in dotted hex notation.
            Warning: 05.01.01 is *only* for Bob Jacobsen's
            python-openlcb (or as otherwise assigned by OpenLCB Group
            which reserves 05.* range). See
            <https://registry.openlcb.org/uniqueidranges>.
    Returns:
        NodeID: A NodeID that is unique (very likely...).
    """
    return NodeID(generate_node_id_str(id_range_prefix))
