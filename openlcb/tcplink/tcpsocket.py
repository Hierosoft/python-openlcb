'''
simple TCP socket input for byte[] send and receive
expects prior setting of host and port variables
'''
# https://docs.python.org/3/howto/sockets.html
import socket

from typing import Union

from openlcb.portinterface import PortInterface


class TcpSocket(PortInterface):
    """TCP socket implementation

    NOTE: This will probably not work in a browser (compiled web
    assembly) since most/all socket features are not in
    WebAssembly System Interface (WASI):
    <https://docs.python.org/3/library/socket.html>

    Args:
        sock (socket.socket, optional): A socket such as from Python's
            builtin socket module. Defaults to a new socket.socket
            instance.
    """
    def __init__(self):
        super(TcpSocket, self).__init__()

    def _settimeout(self, seconds):
        """Set the timeout for connect and transfer.

        Args:
            seconds (float): The number of seconds to wait before
                a timeout error occurs.
        """
        self._device.settimeout(seconds)

    def _connect(self, host, port, device=None):
        # public connect (do not overload) asserts no overlapping call
        if device is None:
            self._device = socket.socket(
                socket.AF_INET,
                socket.SOCK_STREAM,
            )
        else:
            self._device = device

        self._device.connect((host, port))

    def _send(self, data: Union[bytes, bytearray]):
        """Send a single message (bytes)
        Args:
            data (Union[bytes, bytearray]): (list[int] is equivalent
                but not explicitly valid in int range)
        """
        # public send (do not overload) asserts no overlapping call
        # assert isinstance(data, (bytes, bytearray)) # See type hint instead
        total_sent = 0
        while total_sent < len(data[total_sent:]):
            sent = self._device.send(data[total_sent:])
            if sent == 0:
                self.setOpen(False)
                raise RuntimeError("socket connection broken")
            total_sent = total_sent + sent

    def _receive(self) -> bytes:
        '''Receive one or more bytes and return as an [int]
        Blocks until at least one byte is received, but may return more.

        Returns:
            list(int): one or more bytes, converted to a list of ints.
        '''
        # public receive (do not overload) asserts no overlapping call
        data = self._device.recv(128)
        # ^ For block/fail scenarios (based on options previously set) see
        #   <https://manpages.debian.org/bookworm/manpages-dev/recv.2.en.html>
        #   as cited at
        #   <https://docs.python.org/3/library/socket.html#socket.socket.recv>
        if data == b'':
            self.setOpen(False)
            raise RuntimeError("socket connection broken")
        return data

    def _close(self):
        self._device.close()
        return None
