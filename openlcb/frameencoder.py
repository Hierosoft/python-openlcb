from typing import Union


class FrameEncoder:
    def encodeFrameAsString(self, frame) -> str:
        '''Encode frame to string.'''
        raise NotImplementedError("Implement this in each subclass.")

    def encodeFrameAsData(self, frame) -> Union[bytearray, bytes]:
        raise NotImplementedError("Implement this in each subclass.")
