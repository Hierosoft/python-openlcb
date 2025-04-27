'''
Demo of access to and from the link layer.
This is an interface in terms of CAN frames.

Usage:
python3 example_frame_interface.py [host|host:port]

Options:
host|host:port            (optional) Set the address (or using a colon,
                          the address and port). Defaults to a hard-coded test
                          address and port.
'''
# region same code as other examples
from examples_settings import Settings  # do 1st to fix path if no pip install
settings = Settings()

if __name__ == "__main__":
    settings.load_cli_args(docstring=__doc__)
# endregion same code as other examples

from openlcb.canbus.gridconnectobserver import GridConnectObserver
from openlcb.tcplink.tcpsocket import TcpSocket
from openlcb.canbus.canphysicallayergridconnect import (
    CanPhysicalLayerGridConnect,
)
from openlcb.canbus.canframe import CanFrame
from openlcb.canbus.controlframe import ControlFrame

# specify connection information
# region replaced by settings
# host = "192.168.16.212"
# port = 12021
# endregion replaced by settings

sock = TcpSocket()
# s.settimeout(30)
sock.connect(settings['host'], settings['port'])

print("RR, SR are raw socket interface receive and send;"
      " RL, SL are link (frame) interface")


def sendToSocket(frame: CanFrame):
    string = frame.encodeAsString()
    print("   SR: {}".format(string.strip()))
    sock.sendString(string)
    # if frame.afterSendState:
    #     canLink.setState(frame.afterSendState)


def pumpEvents():
    received = sock.receive()
    if settings['trace']:
        observer.push(received)
        if observer.hasNext():
            packet_str = observer.next()
            print("   RR: "+packet_str.strip())
    # pass to link processor
    physicalLayer.handleData(received)
    # canLink.pollState()
    frame = physicalLayer.pollFrame()
    if frame:
        string = frame.encodeAsString()
        print("   SR: {}".format(string.strip()))
        sock.sendString(string)
        if frame.afterSendState:
            print("Next state (unexpected, no link layer): {}"
                  .format(frame.afterSendState))
            # canLink.setState(frame.afterSendState)


def printFrame(frame):
    print("RL: {}".format(frame))


physicalLayer = CanPhysicalLayerGridConnect()
physicalLayer.registerFrameReceivedListener(printFrame)

# send an AME frame with arbitrary alias to provoke response
frame = CanFrame(ControlFrame.AME.value, 1, bytearray())
print("SL: {}".format(frame))
physicalLayer.sendFrameAfter(frame)

while True:
    frame = physicalLayer.pollFrame()
    if not frame:
        break
    sendToSocket(frame)

observer = GridConnectObserver()

# display response - should be RID from nodes
while True:
    pumpEvents()
