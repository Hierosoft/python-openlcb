
from openlcb.canbus.canphysicallayergridconnect import GC_END_BYTE
from openlcb.scanner import Scanner


class GridConnectObserver(Scanner):
    def __init__(self):
        Scanner.__init__(self, delimiter=GC_END_BYTE)
