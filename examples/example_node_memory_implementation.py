'''
Demo of creating a virtual node to represent the application
(other local nodes are possible, but at least one is necessary
for the application to announce itself and provide SNIP info),
in this case with memory to allow another node to change settings
(could also be used to for a second virtual node such as to
represent/emulate a non-LCC train, but a separate
virtual node from the Configuration Tool is recommended in
that case).

based on example_node_implementation from python-openlcb examples.

Usage:
python3 example_node_memory_implementation.py [host|host:port]

Options:
host|host:port            (optional) Set the address (or using a colon,
                          the address and port). Defaults to a hard-coded test
                          address and port.
'''
import os
import socket
import struct
import xml.etree.ElementTree as ET

from logging import getLogger
from typing import Set

# region same code as other examples
from examples_settings import Settings
from openlcb.convert import Convert
from openlcb.localnode import LocalNode
from openlcb.memoryspace import MemorySpace
from openlcb.memorymanager import Segment
settings = Settings()

if __name__ == "__main__":
    settings.load_cli_args(docstring=__doc__)
# endregion same code as other examples

from openlcb import assert_xml, emit_cast, formatted_ex, get_config_dir, prDim, precise_sleep  # noqa: E402, E501
from openlcb.tcplink.tcpsocket import TcpSocket  # noqa: E402

from openlcb.canbus.canphysicallayergridconnect import (  # noqa: E402
    CanPhysicalLayerGridConnect,
)
from openlcb.canbus.canlink import CanLink  # noqa: E402
from openlcb.nodeid import NodeID  # noqa: E402
from openlcb.datagramservice import DatagramReadMemo, DatagramService  # noqa: E402, E501
from openlcb.memoryservice import MemoryService  # noqa: E402
from openlcb.message import Message  # noqa: E402
from openlcb.mti import MTI  # noqa: E402

from openlcb.localnodeprocessor import LocalNodeProcessor  # noqa: E402
from openlcb.pip import PIP  # noqa: E402
from openlcb.snip import SNIP  # noqa: E402
from openlcb.node import Node  # noqa: E402

# specify connection information
# region moved to settings
# host = "192.168.16.212"
# port = 12021
# localNodeID = "05.01.01.01.03.01"
# farNodeID = "09.00.99.03.00.35"
# endregion moved to settings

sock = TcpSocket()
# s.settimeout(30)
try:
    sock.connect(settings['host'], settings['port'])
except socket.gaierror:
    print("Failure accessing {}:{}"
          .format(settings.get('host'), settings.get('port')))
    raise

print("RR, SR are raw socket interface receive and send;"
      " RL, SL are link interface; RM, SM are message interface")

me = os.path.basename(__file__)
logger = getLogger(__name__)

# def sendToSocket(frame: CanFrame):
#     string = frame.encodeAsString()
#     print("      SR: {}".format(string.strip()))
#     sock.sendString(string)
#     physicalLayer.onFrameSent(frame)


def printFrame(frame):
    prDim("   RL: {}".format(frame))


physicalLayer = CanPhysicalLayerGridConnect()
physicalLayer.registerFrameReceivedListener(printFrame)


def printMessage(message: Message):
    prDim(f"RM: {message.mti} from {message.source}")
    # state = canLink.pollState()
    # if state is not CanLink.State.Permitted:
    #     print(f"RM: - SKIPPED (state={state})")
    #     return


localNodeID = NodeID(settings['localNodeID'])
print()
print(f"[example_node_memory_implementation] localNodeID: {localNodeID}")
canLink = CanLink(physicalLayer, localNodeID)
canLink.registerMessageReceivedListener(printMessage)

datagramService = DatagramService(canLink)
canLink.registerMessageReceivedListener(datagramService.process)
port = 12021
spaces = {  # big endian (most significant byte sent first) as per openlcb
    # 0: bytearray([
    #     0x01, 0x00, # 0x1000 = 4096 (unsigned int 16)
    # ])
    0: bytearray(struct.pack(">H", port)),
}
# bytearray allows in-place append (from pack bytes does not)
# H: short (capitalized means unsigned)
# >: big endian (required for openlcb)
# e: float16 (IEEE 754 binary16, 2-bytes)
# For other symbols see Python documentation or SUBTYPE_FORMATS in cdivar.py.

spaces[0] += struct.pack(">e", 0.5)  # save at address 3 (size 2)
# NOTE: 0.5 can be stored precisely, as b'\x008'
#   but not all numbers can be represented by IEEE float.
#   For example, 2.4 is stored as b'\xcd@' which is ~2.400390625

# Additional pack examples:
neg2_float_ba = bytearray(b'\xc0\x00')
neg2_float_b = struct.pack(">e", -2)
assert bytes(neg2_float_ba) == bytes(neg2_float_b), \
    f"expected b'\xc0\x00', b'\xc0\x00', got {neg2_float_ba}, {neg2_float_b}"

cdi = """<?xml version="1.0" encoding="utf-8"?>
<cdi
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://openlcb.org/schema/cdi/1/1/cdi.xsd">
  <identification>
    <manufacturer>python-openlcb example authors</manufacturer>
    <model>example_node_memory_implementation</model>
    <hardwareVersion>1.0</hardwareVersion>
    <softwareVersion>1.0</softwareVersion>
  </identification>
  <acdi/>
  <segment space='0' origin='0'>
    <name>Network Settings</name>
    <description>Behavior of sockets used to connect to the TCP/IP (or serial) to LCC bridge device.</description>
    <group>
      <name>Hub</name>
      <description>How this device connects to the hub.</description>
      <int size="2">
        <name>Port</name>
        <description>Network port of remote hub (2-byte unsigned short)</description>
        <default>12021</default>
      </int>
    </group>
    <group>
      <name>General</name>
      <description>How this device's local socket (TCP/IP or serial) behaves.</description>
      <float size="2">
        <name>Timeout</name>
        <description>Network timeout (2-byte binary16 value).</description>
        <default>0.5</default>
      </float>
    </group>
  </segment>
</cdi>
"""  # noqa: E501


assert_xml(cdi)


def handleDatagram(memo: DatagramReadMemo):
    """create a call-back to print datagram contents when received

    Args:
        memo (DatagramReadMemo): The datagram received

    Returns:
        bool: Always False (True would mean we sent a reply to the datagram,
            but let the MemoryService do that).
    """
    print(f"Datagram receive call back: {Convert.toHex(memo.data)}")
    return False


datagramService.registerDatagramReceivedListener(handleDatagram)

memoryService = MemoryService(datagramService)


# callbacks to get results of memory read

def memoryReadSuccess(memo):
    print("successful memory read: {}".format(memo.data))


def memoryReadFail(memo):
    print("memory read failed: {}".format(memo.data))


# create a node and connect it update
# This node takes part in high level protocols.
# See docstring.
localNode = LocalNode(
    localNodeID,
    canLink,
    snip=SNIP("python-openlcb example authors",
              "example_node_memory_implementation",
              "1.0", "1.0", "example_node_memory_implementation",
              "python-openlcb example node with memory"),
    pipSet=set([
        PIP.SIMPLE_NODE_IDENTIFICATION_PROTOCOL,
        PIP.DATAGRAM_PROTOCOL,
        PIP.CONFIGURATION_DESCRIPTION_INFORMATION,
        PIP.ADCDI_PROTOCOL,
        PIP.MEMORY_CONFIGURATION_PROTOCOL,
    ]),
)

memoryService.memory = localNode
my_conf_dir = os.path.join(get_config_dir("python-openlcb"))
backup_name = "example_node_memory_implementation.cdi.xml"
backup_path = os.path.join(my_conf_dir, backup_name)

localNode.loadCDIString(cdi, backup_path)
# NOTE: loadCDI or loadCDIString sets Element tree and
#   localNode._segments[MemorySpace.CDI.value]
segment = localNode.getSegment(MemorySpace.CDI.value)
assert isinstance(segment, Segment)
assert isinstance(segment._data, (bytearray, bytes))
last = localNode.getLast(0xFF)
assert last is not None
last = localNode.getLast(MemorySpace.CDI)
assert last is not None
# localNodeProcessor = LocalNodeProcessor(canLink, localNode)
# canLink.registerMessageReceivedListener(localNodeProcessor.process)
localNodeProcessor = localNode.localNodeProcessor
localNode.setInt(0, 0, port, 2, False)
localNode.setFloat(0, 2, 0.5, 2)
assert localNode.getSlice(0, 0, 2) == spaces[0][0:2]
assert localNode.getSlice(0, 2, 2) == spaces[0][2:]


def displayOtherNodeIds(message: Message) :
    """Listener to identify connected nodes

    Args:
        message (Message): A response from the network
    """
    if message.mti == MTI.Verified_NodeID :
        print(f"[displayOtherNodeIds] Detected farNodeID {message.source}")
    # For others, see printMessage


canLink.registerMessageReceivedListener(displayOtherNodeIds)


#######################

# have the socket layer report up to bring the link layer up and get an alias

print("      SL : link up...")
physicalLayer.physicalLayerUp()
print("      SL : link up...waiting...")
while canLink.pollState() != CanLink.State.Permitted:
    physicalLayer.receiveAll(sock, verbose=settings['trace'],
                             verbose_fn=prDim)
    physicalLayer.sendAll(sock, verbose=True)
    precise_sleep(.02)
print("      SL : link up")
# request that nodes identify themselves so that we can print their node IDs
message = Message(MTI.Verify_NodeID_Number_Global, localNodeID, None)
canLink.sendMessage(message)

# process resulting activity
while True:
    count = 0
    try:
        count += physicalLayer.sendAll(sock, verbose=True,
                                       verbose_fn=prDim)
        count += physicalLayer.receiveAll(sock, verbose=settings['trace'],
                                          verbose_fn=prDim)
        if count < 1:
            precise_sleep(.01)
        # else skip sleep to avoid latency (port already delayed)
    except Exception:
        print(f"localNodeID={localNodeID}")
        raise

physicalLayer.physicalLayerDown()
