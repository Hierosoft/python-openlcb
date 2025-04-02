
from typing import Union

from openlcb.canbus.canphysicallayergridconnect import GC_END_BYTE


class GridConnectObserver:
    def __init__(self):
        self._buffer = bytearray()
        self._gc_packets = []

    def push(self, data: Union[bytearray, bytes]):
        self._buffer += data
        last_idx = self._buffer.find(GC_END_BYTE)
        if last_idx < 0:  # no ";", packet not yet complete
            return
        packet_bytes = self._buffer[:last_idx+1]  # +1 to keep ";"
        self._buffer = self._buffer[last_idx+1:]  # +1 to discard ";"
        self._onGridConnectFrame(packet_bytes)

    def pop_gc_packet_str(self) -> Union[str, None]:
        if not self._gc_packets:
            return None
        return self.pop_gc_packet().decode("utf-8")

    def pop_gc_packet(self) -> Union[bytearray, None]:
        if not self._gc_packets:
            return None
        return self._gc_packets.pop(0)

    def _onGridConnectFrame(self, data: bytes) -> None:
        self._gc_packets.append(data)
