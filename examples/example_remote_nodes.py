'''
Development demo of a testing skeleton.
This uses a CAN link layer to gather remote node info

Usage:
python3 example_pip_test.py [host|host:port]

Options:
host|host:port            (optional) Set the address (or using a colon,
                          the address and port). Defaults to a hard-coded test
                          address and port.
'''
# region same code as other examples
from timeit import default_timer
from examples_settings import Settings  # do 1st to fix path if no pip install
from openlcb import precise_sleep
from openlcb.canbus.gridconnectobserver import GridConnectObserver
settings = Settings()

if __name__ == "__main__":
    settings.load_cli_args(docstring=__doc__)
# endregion same code as other examples

from openlcb.canbus.canphysicallayergridconnect import (  # noqa:E402
    CanPhysicalLayerGridConnect,
)
# from openlcb.canbus.canframe import CanFrame  # noqa:E402
from openlcb.canbus.canlink import CanLink  # noqa:E402
# from openlcb.canbus.controlframe import ControlFrame  # noqa:E402
from openlcb.tcplink.tcpsocket import TcpSocket  # noqa:E402

from openlcb.node import Node  # noqa:E402
from openlcb.nodeid import NodeID  # noqa:E402
from openlcb.message import Message  # noqa:E402
from openlcb.mti import MTI  # noqa:E402
from openlcb.localnodeprocessor import LocalNodeProcessor  # noqa:E402
from openlcb.pip import PIP  # noqa:E402
from openlcb.remotenodeprocessor import RemoteNodeProcessor  # noqa:E402
from openlcb.remotenodestore import RemoteNodeStore  # noqa:E402
from openlcb.snip import SNIP  # noqa:E402

from queue import Queue  # noqa:E402
from queue import Empty  # noqa:E402

# specify default connection information
# region replaced by settings
# host = "192.168.16.212"
# port = 12021
# localNodeID = "05.01.01.01.03.01"
# trace = False
# timeout = 0.5
# endregion replaced by settings

sock = TcpSocket()
# s.settimeout(30)
sock.connect(settings['host'], settings['port'])

if settings['trace'] :
    print("RR, SR are raw socket interface receive and send;"
          " RL, SL are link (frame) interface")


# def sendToSocket(frame: CanFrame) :
    # string = frame.encodeAsString()
    # if settings['trace'] : print("   SR: "+string.strip())
    # sock.sendString(string)
    # physicalLayer.onFrameSent(frame)


def receiveFrame(frame) :
    if settings['trace']: print("RL: "+str(frame))


physicalLayer = CanPhysicalLayerGridConnect()
physicalLayer.registerFrameReceivedListener(receiveFrame)


def printMessage(msg):
    if settings['trace']: print("RM: {} from {}".format(msg, msg.source))
    readQueue.put(msg)


canLink = CanLink(physicalLayer, NodeID(settings['localNodeID']))
canLink.registerMessageReceivedListener(printMessage)

# create a node and connect it update
# This is a very minimal node, which just takes part in the low-level common
# protocols
localNode = Node(
    NodeID(settings['localNodeID']),
    SNIP("python-openlcb", "example_node_implementation",
         "0.1", "0.2", "User Name Here", "User Description Here"),
    set([PIP.SIMPLE_NODE_IDENTIFICATION_PROTOCOL, PIP.DATAGRAM_PROTOCOL])
)

localNodeProcessor = LocalNodeProcessor(canLink, localNode)
canLink.registerMessageReceivedListener(localNodeProcessor.process)

# arrange for remote nodes to be tracked
remoteNodeStore = RemoteNodeStore(NodeID(settings['localNodeID']))
remoteNodeProcessor = RemoteNodeProcessor(canLink)
remoteNodeStore.processors = [remoteNodeProcessor]
canLink.registerMessageReceivedListener(
    remoteNodeStore.processMessageFromLinkLayer
)

readQueue = Queue()

observer = GridConnectObserver()
_frameReceivedListeners = physicalLayer._frameReceivedListeners
assert len(_frameReceivedListeners) == 1, \
    "{} listener(s) unexpectedly".format(len(_frameReceivedListeners))

# bring the CAN level up

print("* QUEUE Message: link up...")
physicalLayer.physicalLayerUp()
print("  QUEUED Message: link up...waiting for alias reservation...")

# These checks are for debugging. See other examples for simpler pollState loop
cidSequenceStart = default_timer()
previousState = canLink.getState()
print("[main] CanLink previousState={}".format(previousState))
while True:
    # Wait for ready (See also waitForReady)
    state = canLink.getState()
    if state == CanLink.State.Permitted:
        break
    physicalLayer.receiveAll(sock, verbose=settings['trace'])
    physicalLayer.sendAll(sock, verbose=True)


if state != previousState:
    print("[main] CanLink state changed from {} to {}"
          .format(previousState, state))
elif state == CanLink.State.Initial:
    raise NotImplementedError("The CanLink state is still {}".format(state))
else:
    print("[main] CanLink state is still {} before moving on."
          .format(state))

print("nodeIdToAlias: {}".format(canLink.nodeIdToAlias))


def receiveLoop():
    """put the read on a separate thread"""
    while True:
        physicalLayer.receiveAll(sock, verbose=settings['trace'])
        precise_sleep(.01)


import threading  # noqa E402
thread = threading.Thread(daemon=True, target=receiveLoop)


def result(arg1, arg2=None, arg3=None, result=True) :
    """Check and report on test results.

    Args:
        arg1: Any value.
        arg2: value to compare to arg1. Defaults to None.
        arg3: fail if arg1 not equal to arg1; arg3 is then message.
            Defaults to None.
        result (bool, optional): Expected result. Defaults to True.

    Raises:
        ValueError: If only arg1 was provided (undefined behavior--in other
            words, test itself is wrong not the data).

    Returns:
        bool: True if OK, False if failed
    """
    if arg2 is not None :
        if arg1 == arg2 :
            # OK
            print(arg1)
            return True
        else :
            raise ValueError("{} does not equal {}, FAIL".format(arg1, arg2))
            return False
    else:
        print(arg1)
        return result


# start the process
thread.start()


# pull the received messages
while True :
    try :
        received = readQueue.get(True, settings['timeout'])
        if settings['trace'] : print("received: ", received)
    except Empty:
        break

# send an VerifyNodes message to provoke response
print("\nSend Verify NodeID Number Global\n")
message = Message(MTI.Verify_NodeID_Number_Global,
                  NodeID(settings['localNodeID']), None)
if settings['trace'] : print("SM: {}".format(message))
canLink.sendMessage(message)

# pull the received messages
while True :
    try :
        received = readQueue.get(True, settings['timeout'])
        if settings['trace']:
            print("received: ", received)
    except Empty:
        break

# print the resulting node store contents
print("\nDiscovered nodes:")

for node in remoteNodeStore.asArray() :
    print(node, node.snip.manufacturerName, "/",
          node.snip.userProvidedNodeName)

# this ends here, which takes the local node offline

physicalLayer.onDisconnect()
