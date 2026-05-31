
from enum import Enum


class DataFormat(Enum):
    EOF = -1
    Blob = 0
    XML = 1


class DataProcessor:
    """Collect & process consecutive data from each incoming MemoryReadMemo.
    Superclass for data listeners.

    Attributes:
        enable_cache (bool): Defaults to False (May differ in subclass).
    """
    DEFAULT_EXT = ".bin"  # override in subclass

    def __init__(self):
        self._is_from_cache = False  # type: bool
        self._path = None  # type: str|None
        self.enable_cache = False  # type: bool
        # Members used to construct space memo such as CDIMemo:
        self.progress_ratio = None  # type: float|None
        self.progress_count = None  # type: int|None
        self.expected_size = None  # type: int|None

    def getPath(self):
        return self._path

    def isFromCache(self):
        return self._is_from_cache
