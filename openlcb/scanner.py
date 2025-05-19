
from logging import getLogger
from typing import Union

from openlcb import emit_cast

logger = getLogger(__name__)


class Scanner:
    """Collect bytes and check for a token
    (Similar to Scanner class in Java)

    Attributes:
        EOF: If delimiter is set to this, then regardless of _buffer
            type if len(_buffer) > 0 then get all data (and trigger
            _onHasNext on every push). Mimic Java behavior where
            "\\Z" can be added as the delimiter for EOF.
    """
    EOF = "\\Z"  # must *not* be a valid byte (special case, not searched)

    def __init__(self, delimiter=EOF):
        self._delimiter = delimiter
        self._buffer = bytearray()

    def push(self, data: Union[bytearray, bytes, int]):
        if isinstance(data, int):
            self._buffer.append(data)
        else:
            self._buffer += data
        if self._delimiter == Scanner.EOF:
            self._onHasNext()
            return
        self.assertDelimiterType()
        last_idx = self._buffer.find(self._delimiter)
        if last_idx < 0:  # no ";", packet not yet complete
            return
        self._onHasNext()

    def nextByte(self) -> int:
        if not self._buffer:
            raise EOFError("No more bytes (_buffer={})"
                           .format(emit_cast(self._buffer)))
        if not isinstance(self._buffer, (bytes, bytearray)):
            raise TypeError("Buffer is {} (nextByte is for bytes/bytearray)"
                            .format(type(self._buffer).__name__))
        result = self._buffer[0]
        del self._buffer[0]
        return result

    def hasNextByte(self) -> bool:
        return True if self._buffer else False

    def hasNext(self) -> bool:
        if self._delimiter == Scanner.EOF:
            return self.hasNextByte()
        return self._delimiter in self._buffer

    def next(self) -> str:
        self.assertDelimiterType()
        return self.nextBytes().decode("utf-8")

    def assertDelimiterType(self):
        """Assert that delimiter is correct type for _buffer.find arg,
        or is Scanner.EOF which does not trigger find.
        """
        if self._delimiter == Scanner.EOF:
            return  # OK since EOF doesn't trigger find in _buffer
        if isinstance(self._buffer, (bytes, bytearray)):
            assert isinstance(self._delimiter, (int, bytes, bytearray))
        else:
            assert isinstance(
                self._delimiter,
                (type(self._buffer[0]), type(self._buffer[0:1]))
            )

    def nextBytes(self) -> bytearray:
        if not self._buffer:
            raise EOFError(
                "There are no bytes in the buffer."
                " Check hasNext first or handle this exception"
                " in client code.")
        assert isinstance(self._buffer, (bytes, bytearray))
        if self._delimiter == Scanner.EOF:
            result = self._buffer
            self._buffer = type(self._buffer)()  # a.k.a. .copy()
            #  (bytearray has .copy but bytes does not, so use constructor)
            return result
        self.assertDelimiterType()
        last_idx = self._buffer.find(self._delimiter)
        if last_idx < 0:  # no ";", packet not yet complete
            raise EOFError(
                "Delimiter not found before EOF."
                " Check hasNext first or handle this exception"
                " in client code.")
        # logger.debug("Getting {} to {} exclusive of {} in {}"
        #              .format(0, last_idx+1, len(self._buffer),
        #                      emit_cast(self._buffer)))
        # logger.debug("Leaving {} to {} exclusive of {}"
        #              .format(last_idx+1, len(self._buffer),
        #                      len(self._buffer)))
        packet_bytes = self._buffer[:last_idx+1]  # +1 to keep ";"
        self._buffer = self._buffer[last_idx+1:]  # +1 to discard ";"
        return packet_bytes

    def _onHasNext(self) -> None:
        """abstract handler (occurs immediately on push)
        If overridden/polyfilled, this is the soonest possible time to
        call next (It is guaranteed to not throw EOFError at this
        point, barring threads incorrectly calling next after this
        method starts but before it ends, and as long as you handle
        it right away and don't allow push to trigger another call
        before the implementation of this calls next).
        """
        pass  # next_str = self.next
