
from enum import Enum


class DataFormat(Enum):
    EOF = 0
    XML = 1


class DataProcessor:
    """Collect & process consecutive data from each incoming MemoryReadMemo.
    Superclass for data listeners.
    """
    def __init__(self):
        pass
