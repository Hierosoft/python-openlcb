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
from examples_settings import Settings
from openlcb import precise_sleep
from openlcb.canbus.gridconnectobserver import GridConnectObserver  # do 1st to fix path if no pip install
settings = Settings()

if __name__ == "__main__":
    settings.load_cli_args(docstring=__doc__)
# endregion same code as other examples

from openlcb.canbus.canphysicallayergridconnect import (
    CanPhysicalLayerGridConnect,
)
# from openlcb.canbus.canframe import CanFrame
from openlcb.canbus.canlink import CanLink
# from openlcb.canbus.controlframe import ControlFrame
from openlcb.tcplink.tcpsocket import TcpSocket

from openlcb.node import Node
from openlcb.nodeid import NodeID
from openlcb.message import Message
from openlcb.mti import MTI
from openlcb.localnodeprocessor import LocalNodeProcessor
from openlcb.pip import PIP
from openlcb.remotenodeprocessor import RemoteNodeProcessor
from openlcb.remotenodestore import RemoteNodeStore
from openlcb.snip import SNIP

from queue import Queue
from queue import Empty

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
    # physicalLayer.onSentFrame(frame)


def receiveFrame(frame) :
    if settings['trace']: print("RL: "+str(frame))


physicalLayer = CanPhysicalLayerGridConnect()
physicalLayer.registerFrameReceivedListener(receiveFrame)


def printMessage(msg):
    if settings['trace']: print("RM: {} from {}".format(msg, msg.source))
    readQueue.put(msg)


canLink = CanLink(physicalLayer, NodeID(settings['localNodeID']),
                  require_remote_nodes=True)
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

assert len(physicalLayer.listeners) == 1, \
    "{} listener(s) unexpectedly".format(len(physicalLayer.listeners))


def pumpEvents():
    received = sock.receive()
    if received is not None:
        # may be None if socket.setblocking(False) mode
        if settings['trace']:
            observer.push(received)
            if observer.hasNext():
                packet_str = observer.next()
                print("+ RECEIVED Remote: "+packet_str.strip())
        # pass to link processor
        physicalLayer.handleData(received)
    canLink.pollState()

    while True:
        frame = physicalLayer.pollFrame()
        if frame is None:
            break
        string = frame.encodeAsString()
        if True:  # if settings['trace']:
            print("- SENT Remote: "+string.strip())
        sock.sendString(string)
        physicalLayer.onSentFrame(frame)


# bring the CAN level up

print("* QUEUE Message: link up...")
physicalLayer.physicalLayerUp()
print("  QUEUED Message: link up...waiting for alias reservation"
      " (canLink.require_remote_nodes={})..."
      .format(canLink.require_remote_nodes))

# These checks are for debugging. See other examples for simpler pollState loop
cidSequenceStart = default_timer()
previousState = canLink.getState()
print("[main] CanLink previousState={}".format(previousState))
while True:
    # This is a pollState loop as our custom pumpEvents function
    #   calls pollState.
    state = canLink.getState()
    if state != previousState:
        print("[main] CanLink state changed from {} to {}"
              .format(previousState, state))
        previousState = state
    if state == CanLink.State.Permitted:
        break
    pumpEvents()
    state = canLink.getState()
    if state != previousState:
        print("[main] CanLink state changed from {} to {}"
              .format(previousState, state))
        previousState = state

    precise_sleep(.02)
    if default_timer() - cidSequenceStart > 2:  # measured in seconds
        print("[main] Warning, no response received, assuming no remote nodes"
              " continuing alias reservation"
              " (ok to do so after 200ms"
              " according to CAN Frame Transfer - Standard)")
        break
    state = canLink.getState()

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
        pumpEvents()
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
        if settings['trace'] : print("received: ", received)
    except Empty:
        break

# print the resulting node store contents
print("\nDiscovered nodes:")

for node in remoteNodeStore.asArray() :
    print(node, node.snip.manufacturerName, "/",
          node.snip.userProvidedNodeName)

# this ends here, which takes the local node offline

canLink.onDisconnect()
