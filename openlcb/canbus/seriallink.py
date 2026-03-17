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
# TODO: use non-blocking mode and eliminate MSGLEN, since MSGLEN is only
#   a convenience for CLI programs (PhysicalLayer is able to assemble
#   packets from arbitrary chunks) and GridConnectObserver can replace
#   that.


class SerialLink(PortInterface):
    """simple serial input for string send and receive"""
    def __init__(self):
        super(SerialLink, self).__init__()

    def _settimeout(self, seconds: float):
        logger.warning("settimeout is not implemented for SerialLink")
        pass

    def _connect(self, _, port: str, device: Union[serial.Serial, None] = None,
                 baudrate: int = 230400):
        """Connect to a serial port.

        Args:
            _ (NoneType): Host (Unused since host is always local
                machine for serial; placeholder for
                compatibility with the interface).
            port (str): A string that identifies a serial port for the
                serial.Serial constructor.
            baudrate (int, optional): Desired serial speed. Defaults to
                230400 bits per second.
            device (serial.Serial): Existing hardware abstraction.
                Defaults to serial.Serial(port, baudrate).
        """
        assert _ is None, "Serial ports are always on machine not {}".format(_)
        # ^ Use None or connectLocal for non-network connections.
        if device is None:
            self._device = serial.Serial(port, baudrate)
        else:
            self._device = device
        self._device.reset_input_buffer()  # drop anything that's just sitting there already  # noqa: E501

    def _send(self, data: Union[bytes, bytearray]) -> None:
        """send bytes

        Args:
            data (Union[bytes,bytearray]): data such as a GridConnect
                string encoded as utf-8.

        Raises:
            RuntimeError: If the string couldn't be written to the port.
        """
        total_sent = 0
        while total_sent < len(data[total_sent:]):
            sent = self._device.write(data[total_sent:])
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
            chunk = self._device.read(1)
            if chunk == b'':
                self.setOpen(False)
                raise RuntimeError("serial connection broken")
            data.extend(chunk)
            bytes_recd = bytes_recd + len(chunk)
            if GC_END_BYTE in chunk:
                break
        return data

    def _close(self):
        self._device.close()
        return
