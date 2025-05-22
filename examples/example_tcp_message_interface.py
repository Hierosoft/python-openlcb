'''
Demo of access to and from the message layer using a native TCP connection

This is an interface in terms of OpenLCB messages.

Usage:
python3 example_tcp_message_interface.py [host|host:port]

Options:
host|host:port            (optional) Set the address (or using a colon,
                          the address and port). Defaults to a hard-coded test
                          address and port.
'''
from logging import getLogger
# region same code as other examples
from examples_settings import Settings  # do 1st to fix path if no pip install
from openlcb import precise_sleep
from openlcb.realtimephysicallayer import RealtimePhysicalLayer
settings = Settings()

if __name__ == "__main__":
    settings.load_cli_args(docstring=__doc__)
# endregion same code as other examples

from openlcb.tcplink.tcpsocket import TcpSocket  # noqa: E402
from openlcb.tcplink.tcplink import TcpLink  # noqa: E402

from openlcb.nodeid import NodeID  # noqa: E402
from openlcb.message import Message  # noqa: E402
from openlcb.mti import MTI  # noqa: E402

if __name__ == "__main__":
    logger = getLogger(__file__)
else:
    logger = getLogger(__name__)

# specify connection information
# region moved to settings
# host = "localhost"
# port = 12022
# localNodeID = "05.01.01.01.03.01"
# endregion moved to settings

sock = TcpSocket()
# s.settimeout(30)
print("Using settings:")
print(settings.dumps())
sock.connect(settings['host'], settings['port'])

print("RR, SR are raw socket interface receive and send; "
      " RM, SM are message interface")


# def sendToSocket(data: Union(bytes, bytearray)):
#     assert isinstance(data, (bytes, bytearray))
#     print("      SR: {}".format(data))
#     sock.send(data)
# ^ Moved to RealtimePhysicalLayer sendFrameAfter override


def printMessage(msg):
    print("RM: {} from {}".format(msg, msg.source))


physicalLayer = RealtimePhysicalLayer(sock)
# ^ this was not in the example before
# (just gave sendToSocket to TcpLink)

tcpLinkLayer = TcpLink(physicalLayer, NodeID(100))
tcpLinkLayer.registerMessageReceivedListener(printMessage)

#######################

# have the socket layer report up to bring the link layer up and get an alias
print("      SL : link up...")
tcpLinkLayer.linkUp()
print("      SL : link up")

# send an VerifyNodes message to provoke response
message = Message(MTI.Verify_NodeID_Number_Global,
                  NodeID(settings['localNodeID']), None)
print("SM: {}".format(message))
tcpLinkLayer.sendMessage(message)

# N/A
# while not tcpLinkLayer.getState() == TcpLink.State.Permitted:
#     time.sleep(.02)

# process resulting activity
while True:
    count = 0
    received = sock.receive()
    if received is not None:
        print("      RR: {}".format(received))
        # pass to link processor
        tcpLinkLayer.handleFrameReceived(received)
        count += 1
    # count += physicalLayer.sendAll(sock)  # typical but N/A since realtime
    if count < 1:
        precise_sleep(.01)
    # else skip sleep to avoid latency (port already delayed)
