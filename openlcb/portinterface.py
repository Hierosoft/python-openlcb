"""Thread-safe port interface.

In threading scenarios, trying to send and receive at the same time
results in undefined behavior (at OS-level serial or socket
implementation).

Therefore, all port implementations must inherit this if threads are used,
and threads must be used in a typical implementation
- Unless: alias reservation sequence is split into separate events
  and handleData will run, in a non-blocking manner, before each send
  call in defineAndReserveAlias.
"""
from logging import getLogger
from typing import Any, Union

logger = getLogger(__name__)


class PortInterface:
    """Manage send and receive in a thread-safe way.

    In each subclass:
    - The private methods must be overridden.
    - Set self._open to False on any exception that indicates a
      disconnect.
    - The public methods must *not* be overridden unless there are
      similar measures taken to prevent send and recv from occurring at
      once (on different threads), which would cause undefined behavior
      (in OS-level implementation of serial port or socket).
    """

    def __init__(self):
        """This must run for each subclass, such as using super"""
        self._busy_message = None
        self._open = False
        self._onReadyToSend = None
        self._onReadyToReceive = None
        self._device = None

    def busy(self) -> bool:
        return self._busy_message is not None

    def _setBusy(self, caller):
        self.assertNotBusy(caller)
        self._busy_message = caller

    def _unsetBusy(self, caller):
        if caller != self._busy_message:
            raise InterruptedError(
                "Untracked {} ended during {}"
                " Check busy() first or setListeners"
                " (implementation problem: See OpenLCBNetwork"
                " for correct example)"
                .format(caller, self._busy_message))
        self._busy_message = None

    def assertNotBusy(self, caller):
        if self._busy_message:
            raise InterruptedError(
                "{} was called during {}."
                " Check busy() first or setListeners"
                " and wait for {} ready"
                " (or use OpenLCBNetwork to send&receive)"
                .format(caller, self._busy_message, caller))

    def setListeners(self, onReadyToSend, onReadyToReceive):
        self._onReadyToReceive = onReadyToReceive
        self._onReadyToSend = onReadyToSend

    def _settimeout(self, seconds):
        """Abstract method. Return: implementation-specific or None."""
        raise NotImplementedError("Subclass must implement this.")

    def settimeout(self, seconds):
        return self._settimeout(seconds)

    def _connect(self, host: Any, port: Any, device: Any = None):
        """Abstract interface. Return: implementation-specific or None
        See connect for details.
        raise exception on failure to prevent self._open = True.
        """
        raise NotImplementedError("Subclass must implement this.")

    def connect(self, host, port, device=None):
        """Connect to a port.

        Args:
            host (str): hostname/IP, or None for local such as in serial
                implementation.
            port (Union[int, str]): Port number (int for network
                implementation, str for serial implementation, such as
                "COM1" or other on Windows or "/dev/" followed by port
                path on other operating systems)
            device (Union[socket.socket, serial.Serial, None]): Existing
                hardware abstraction: Type depends on implementation.
        """
        self._setBusy("connect")
        result = self._connect(host, port, device=device)
        self.setOpen(True)
        self._unsetBusy("connect")
        return result  # may be implementation-specific

    def connectLocal(self, port):
        """Convenience method for connecting local port such as serial
        (where host is not applicable since host is this machine).
        See connect for documentation, but host is None in this case.
        """
        self.connect(None, port)

    def _send(self, data: Union[bytes, bytearray]) -> None:
        """Abstract method. Return: implementation-specific or None"""
        raise NotImplementedError("Subclass must implement this.")

    def send(self, data: Union[bytes, bytearray]) -> None:
        """

        Raises:
            InterruptedError: (raised by assertNotBusy) if
                port is in use. Use sendFrameAfter to avoid this.

        Args:
            data (Union[bytes, bytearray]): _description_
        """
        self._setBusy("send")
        self._busy_message = "send"
        try:
            self._send(data)
        finally:
            self._unsetBusy("send")
            if self._onReadyToReceive:
                self._onReadyToReceive()

    def _receive(self) -> Union[bytearray, bytes, None]:
        """Abstract method. Return (bytes): data"""
        raise NotImplementedError("Subclass must implement this.")

    def receive(self) -> Union[bytearray, bytes, None]:
        self._setBusy("receive")
        result = None
        try:
            result = self._receive()
        finally:
            self._unsetBusy("receive")
            if self._onReadyToSend:
                self._onReadyToSend()
        return result

    def _close(self) -> None:
        """Abstract method. Return: implementation-specific or None"""
        raise NotImplementedError("Subclass must implement this.")

    def setOpen(self, is_open):
        if self._open != is_open:
            logger.warning(
                "{} open state changing from {} to {}"
                .format(type(self).__name__, self._open, is_open))
            self._open = is_open
        else:
            logger.warning("Port open state already {}".format(self._open))

    def close(self) -> None:
        return self._close()

    # replaced with pollFrame
    # def receiveString(self):
    #     '''Receive (usually partial) GridConnect frame and return as string.

    #     Returns:
    #         str: The received bytes decoded into a UTF-8 string.
    #     '''
    #     data = self.receive()
    #     # Use receive (has required semaphores) not _receive--not thread safe
    #     return data.decode("utf-8")

    def sendString(self, string: str):
        """Send a single string.
        """
        self.send(string.encode('utf-8'))
        # Use send (uses required semaphores) not _send (not thread safe)
