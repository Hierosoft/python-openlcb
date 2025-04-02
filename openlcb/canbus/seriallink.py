'''
simple serial input for string send and receive
expects prior setting of device name
'''
import serial

from logging import getLogger
from typing import Union

from openlcb.canbus.canphysicallayergridconnect import GC_END_BYTE
from openlcb.portinterface import PortInterface

logger = getLogger(__name__)

MSGLEN = 35


class SerialLink(PortInterface):
    """simple serial input for string send and receive"""
    def __init__(self):
        super(SerialLink, self).__init__()

    def _settimeout(self, seconds):
        logger.warning("settimeout is not implemented for SerialLink")
        pass

    def _connect(self, _, device, baudrate=230400):
        """Connect to a serial port.

        Args:
            _ (NoneType): Host (Unused since host is always local
                machine for serial; placeholder for
                compatibility with the interface).
            device (str): A string that identifies a serial port for the
                serial.Serial constructor.
            baudrate (int, optional): Desired serial speed. Defaults to
                230400 bits per second.
        """
        self.port = serial.Serial(device, baudrate)
        self.port.reset_input_buffer()  # drop anything that's just sitting there already  # noqa: E501

    def _send(self, msg: Union[bytes, bytearray]):
        """send bytes

        Args:
            data (Union[bytes,bytearray]): data such as a GridConnect
                string encoded as utf-8.

        Raises:
            RuntimeError: If the string couldn't be written to the port.
        """
        total_sent = 0
        while total_sent < len(msg[total_sent:]):
            sent = self.port.write(msg[total_sent:])
            if sent == 0:
                self.setOpen(False)
                raise RuntimeError("socket connection broken")
            total_sent = total_sent + sent

    def _receive(self) -> bytearray:
        '''Receive data

        Returns:
            bytearray: A (usually partial) GridConnect frame
        '''
        data = bytearray()
        bytes_recd = 0
        while bytes_recd < MSGLEN:
            chunk = self.port.read(1)
            if chunk == b'':
                self.setOpen(False)
                raise RuntimeError("serial connection broken")
            data.extend(chunk)
            bytes_recd = bytes_recd + len(chunk)
            if GC_END_BYTE in chunk:
                break
        return data

    def _close(self):
        self.port.close()
        return
