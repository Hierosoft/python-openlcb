'''
Generalize access to the physical layer;.

Parent of `CanPhysicalLayer`

'''


class PhysicalLayer:
    def physicalLayerUp(self):
        """abstract method"""
        raise NotImplementedError("Each subclass must implement this.")

    def physicalLayerRestart(self):
        """abstract method"""
        raise NotImplementedError("Each subclass must implement this.")

    def physicalLayerDown(self):
        """abstract method"""
        raise NotImplementedError("Each subclass must implement this.")

    def encodeFrameAsString(self, frame):
        raise NotImplementedError("Each subclass must implement this.")