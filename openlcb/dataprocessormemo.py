from typing import Union

from openlcb.message import Message


class DataProcessorMemo:
    """Store parsing state info.
    This superclass can be used for progress notification.

    Attributes:
        complete_data (bytearray|None): Set if done, for debugging
            (such as parser error without details).
        done (bool): If True, download such as downloadCDI is finished.
            Though document itself may be incomplete if 'error' is also
            set, stop tracking status of download regardless.
        end (bool): False to start a deeper scope, or True for end tag,
            which exits current scope (last created Treeview branch in
            this case, or top if getBranch() would be None).
        error (str): Message of failure (requires 'done' if stopped).
        message (Message): Associated network/internal message.
        name (str): Name (determined by `name` child element content).
        status (str): Status message.
    """
    def __init__(self, status: Union[str, None] = None):
        self.done = False  # type: bool
        self.complete_data = None  # type: bytearray|None
        self.end = False  # type: bool
        self.error = None  # type: str|None
        self.message: Union[Message, None] = None  # type: Message|None
        self.status = status   # type: str|None
        # region set by DataProcessor such as XMLDataProcessor
        self.progress_ratio = None  # type: float|None
        self.progress_count = None  # type: int|None
        self.expected_size = None  # type: int|None
        # end region set by DataProcessor such as XMLDataProcessor
