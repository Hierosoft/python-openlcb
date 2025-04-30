'''
Simulated CanPhysicalLayer to record frames requested to be sent.
'''

from openlcb.canbus.canphysicallayer import CanPhysicalLayer


class CanPhysicalLayerSimulation(CanPhysicalLayer):

    def __init__(self):
        self.receivedPackets = []
        CanPhysicalLayer.__init__(self)

    def handlePacket(self, frame):
        self.receivedPackets.append(frame)
