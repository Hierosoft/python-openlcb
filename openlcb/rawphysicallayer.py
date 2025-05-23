from typing import Union
from openlcb.frameencoder import FrameEncoder
from openlcb.physicallayer import PhysicalLayer


class RawPhysicalLayer(PhysicalLayer, FrameEncoder):
    """Implements FrameEncoder but leaves PhysicalLayer untouched
    so that PhysicalLayer methods can be implemented by subclass or
    sibling class used as second superclass by subclass.
    - This FrameEncoder implementation doesn't actually
      encode CanFrame--only converts between str & bytes!
    """
    def __init__(self, *args, **kwargs):
        PhysicalLayer.__init__(self, *args, **kwargs)
        FrameEncoder.__init__(self, *args, **kwargs)

    def encodeFrameAsString(self, frame) -> str:
        if isinstance(frame, str):
            return frame
        elif isinstance(frame, (bytearray, bytes)):
            return frame.decode("utf-8")
        raise TypeError(
            "Only str, bytes, or bytearray is allowed for RawPhysicalLayer."
            " For {} use/make another Encoder implementation."
            .format(type(self).__name__))

    def encodeFrameAsData(self, frame) -> Union[bytearray, bytes]:
        if isinstance(frame, str):
            return frame.encode("utf-8")
        elif isinstance(frame, (bytearray, bytes)):
            return frame
        raise TypeError(
            "Only str, bytes, or bytearray is allowed for RawPhysicalLayer."
            " For frame type {} use/make another FrameEncoder implementation."
            .format(type(self).__name__))
