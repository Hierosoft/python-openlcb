import os
import socket
import ipaddress
from typing import Optional

from logging import getLogger

from openlcb import (
    only_hex_pairs,
    emit_cast,
)

logger = getLogger(__name__)

LCC_ID_SEP = "."


def hex_to_dotted_lcc_id(hex_s):
    if (not isinstance(hex_s, str)) or (len(hex_s) != 12):
        raise ValueError(
            "Only 6 hex pairs (12 characters) allowed, but got {}."
            .format(emit_cast(hex_s)))
    return LCC_ID_SEP.join([hex_s[i*2:i*2+2] for i in range(len(hex_s)//2)])


def validate_lcc_id(lcc_id_s):
    """Convert an LCC ID in dot notation to a hex and error pair.
    Get a tuple of a hex string and a validation error (or None)
    suitable for form validation (Done that way so this is the
    only function that does LCC ID analysis).

    Args:
        lcc_id_s (str): An LCC ID string. Examples: 02.01.57.00.04.9C or
            2.1.57.0.4.9C (both give same 12-digit hex string).

    Returns:
        tuple(str, str): tuple of hex string and error:
        - Hex string is 12 characters uppercase, or None if input is bad.
        - Error is only not None if hex string is None.
    """
    if not lcc_id_s:
        error = "[dotted_lcc_id_to_hex] Got {}".format(repr(lcc_id_s))
        # ^ repr shows '' or None
        return None, error
    parts = lcc_id_s.split(".")
    if len(parts) != 6:
        error = "Not 6 parts: {}".format(lcc_id_s)
        return None, error
    hex_s = ""
    for part in parts:
        if len(part) == 2:
            hex_s += part
        elif len(part) == 1:  # Add leading 0 since not required.
            hex_s += "0" + part
        elif len(part) < 1:
            error = "Extra '.' in {} (not an LCC ID)".format(repr(lcc_id_s))
            return None, error
        else:
            error = "Wrong length for {}".format(repr(part))
            return None, error
    if not only_hex_pairs(hex_s):
        error = "Non-hex found in {} (expected 0-9/A-F)".format(repr(lcc_id_s))
        return None, error
    return hex_s.upper(), None


def dotted_lcc_id_to_hex(lcc_id_s):
    hex_s, error = validate_lcc_id(lcc_id_s)
    if error:
        logger.info(error)
        return None
    return hex_s


def is_hex_lcc_id(value):
    """Check if it is a 12-character LCC ID in pure hex format.
    Uppercase or lowercase is valid if 12 characters. If dotted, you
    must first use dotted_lcc_id_to_hex to make it machine readable
    (including to add zero padding) or see if result is None from that
    before calling this.
    """
    # if (len(value) < 12) and (len(value) >= minimum_length):
    #     value = value.zfill(12)  # pad left with zeroes
    # ^ Commented since dotted_lcc_id_to_hex can be used to get
    #   a clean one if possible.
    if len(value) != 12:
        logger.info("Not 12 characters: {}".format(value))
        return False

    return only_hex_pairs(value)


def is_dotted_lcc_id(value):
    """It is an LCC ID in dot notation (human readable)
    Examples: 02.01.57.00.04.9C or 2.1.57.0.4.9C (same effect)

    To generate LCC IDs, first allocate a range at
    https://registry.openlcb.org/uniqueidranges
    """
    hex_str = dotted_lcc_id_to_hex(value)
    if not hex_str:  # warning/info logged by dotted_lcc_id_to_hex
        return False
    return only_hex_pairs(hex_str)


def get_process_id() -> int:
    """Get current process ID."""
    return os.getpid()


def get_local_ip() -> Optional[str]:
    """
    Try to find a non-loopback IPv4 address.
    Returns '127.0.0.1' as fallback.
    """
    try:
        # Create a dummy UDP socket just to get routing information
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Doesn't need to actually connect
        #   - just used to find default interface
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()

        # Make sure it's not loopback
        if ipaddress.ip_address(ip).is_loopback:
            return None

        return ip
    except Exception:
        pass

    # Fallback: try to enumerate interfaces
    try:
        for iface in socket.getaddrinfo(socket.gethostname(), None,
                                        socket.AF_INET):
            addr = iface[4][0]
            if not ipaddress.ip_address(addr).is_loopback:
                return addr
    except Exception:
        pass

    return "127.0.0.1"


def generate_last_three_octets() -> bytearray:
    """Generate 3 hex octets from hash of (ip + pid)"""
    ip = get_local_ip() or "127.0.0.1"
    pid = get_process_id()

    seed = f"{ip}:{pid}"

    # Using hash() gives a signed 64-bit value in CPython
    # We take abs() and then mask to 32 bits for consistency
    h = abs(hash(seed)) & 0xFFFFFFFF

    # Extract 3 bytes
    return bytearray([
        (h >> 16) & 0xFF,
        (h >> 8)  & 0xFF,
        h         & 0xFF,
    ])


def generate_last_three_octets_str() -> str:
    octets = generate_last_three_octets()
    return f"{octets[0]:02x}.{octets[1]:02x}.{octets[2]:02x}"


def generate_node_id_str(id_range_prefix) -> str:
    """Generate a unique NodeID string for the session to ensure each
    instance (even of python-openlcb on same device) or
    locally-generated virtual node is unique.

    Args:
        id_range_prefix (str): NodeID prefix in dotted hex notation
            (3 to 5. 3 at most recommended to make uniqueness more
            likely) Warning: 05.01.01 is *only* for Bob Jacobsen's
            python-openlcb (or as otherwise assigned by OpenLCB Group
            which reserves 05.* range) See
            <https://registry.openlcb.org/uniqueidranges>.
    Returns:
        str: Full 48-bit node ID in dotted hex string notation (Example:
            '05.01.01.4A.B7.19') that is unique (very likely...).
    """

    lastParts = [f"{p:02X}" for p in generate_last_three_octets()]
    assert len(lastParts) == 3
    prefixParts = id_range_prefix.split(".")
    if len(prefixParts) < 3:
        raise ValueError(
            "Please specify at least 3 hex pairs separated by '.'. Got {}"
            .format(id_range_prefix))
    if len(prefixParts) > 5:
        raise ValueError(
            "Please specify at most 5 hex pairs separated by '.'"
            " (preferably less to increase likelihood of uniqueness). Got {}"
            .format(id_range_prefix))
    uniqueCount = 6 - len(prefixParts)
    return ".".join(prefixParts+lastParts[-uniqueCount:])
    # ^ negative to keep last uniqueCount pairs
