'''
Demo of access to and from the message layer, i.e. down through the link layer

This is an interface in terms of OpenLCB messages.

Usage:
python3 example_message_interface.py [host|host:port]

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

from openlcb import precise_sleep  # noqa: E402
from openlcb.tcplink.tcpsocket import TcpSocket  # noqa: E402

from openlcb.canbus.canphysicallayergridconnect import (  # noqa: E402
    CanPhysicalLayerGridConnect,
)
from openlcb.canbus.canlink import CanLink  # noqa: E402
from openlcb.nodeid import NodeID  # noqa: E402
from openlcb.message import Message  # noqa: E402
from openlcb.mti import MTI  # noqa: E402

# specify connection information
# region replaced by settings
# host = "192.168.16.212"
# port = 12021
# localNodeID = "05.01.01.01.03.01"
# endregion replaced by settings

sock = TcpSocket()
# s.settimeout(30)
sock.connect(settings['host'], settings['port'])

print("RR, SR are raw socket interface receive and send; RL,"
      " SL are link interface; RM, SM are message interface")


# def sendToSocket(frame: CanFrame):
#     string = frame.encodeAsString()
#     print("      SR: {}".format(string.strip()))
#     sock.sendString(string)
#     physicalLayer.onFrameSent(frame)


def printFrame(frame):
    print("   RL: {}".format(frame))


physicalLayer = CanPhysicalLayerGridConnect()
physicalLayer.registerFrameReceivedListener(printFrame)


def printMessage(msg):
    print("RM: {} from {}".format(msg, msg.source))


canLink = CanLink(physicalLayer, NodeID(settings['localNodeID']))
canLink.registerMessageReceivedListener(printMessage)

#######################

# have the socket layer report up to bring the link layer up and get an alias


print("      SL : link up...")
physicalLayer.physicalLayerUp()
print("      SL : link up...waiting...")
physicalLayer.physicalLayerUp()
while canLink.pollState() != CanLink.State.Permitted:
    physicalLayer.receiveAll(sock, verbose=settings['trace'])
    physicalLayer.sendAll(sock, verbose=True)
    precise_sleep(.02)
print("      SL : link up")
# send an VerifyNodes message to provoke response
message = Message(MTI.Verify_NodeID_Number_Global,
                  NodeID(settings['localNodeID']), None)
print("SM: {}".format(message))
canLink.sendMessage(message)

# process resulting activity
while True:
    physicalLayer.receiveAll(sock, verbose=settings['trace'])
    physicalLayer.sendAll(sock, verbose=True)
    precise_sleep(.01)

physicalLayer.onDisconnect()
