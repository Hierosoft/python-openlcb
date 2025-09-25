# from logging import getLogger
from typing import (
    Dict,
    List,  # in case list doesn't support `[` in this Python version
    Union,  # in case `|` doesn't support 'type' in this Python version
)

from openlcb.message import Message
from openlcb.node import Node
from openlcb.nodeid import NodeID
from openlcb.processor import Processor

# logger = getLogger(__name__)


class NodeStore :
    '''
    Store the available Nodes and provide multiple means of retrieval.

    Storage and indexing methods are an internal detail.
    You can't remove a node; once we know about it, we know about it.
    '''

    def __init__(self) :
        self.byIdMap: Dict[NodeID, Node] = {}
        self.nodes: List[Node] = []
        self.processors: List[Processor] = []

    # Store a new node or replace an existing stored node
    # - Parameter node: new Node content
    def store(self, node: Node) :
        self.byIdMap[node.id] = node
        self.nodes.append(node)

        # sort by SNIP user name (ascending, blanks at front)
        # This can be too early, when node created but no SNIP yet,
        #   so also sort before use in View
        self.nodes.sort(key=lambda x: x.snip.userProvidedNodeName,
                        reverse=True)

    def isPresent(self, nodeID: NodeID) -> bool:
        return self.byIdMap.get(nodeID) is not None

    def asArray(self) -> List[Node]:
        return [self.byIdMap[i] for i in self.byIdMap]

    # Retrieve a Node's content from the store
    # - Parameter is either
    #     userProvidedDescription: string to match SNIP content
    #     nodeID: for direct lookup
    # - Returns: None if the there's no match
    def lookup(self, parm: Union[NodeID, str]) -> Node:
        if isinstance(parm, NodeID) :
            if parm not in self.byIdMap :
                self.byIdMap[parm] = None
            return self.byIdMap[parm]
        # assume parm is string
        for node in self.byIdMap.values() :
            if (node.snip.userProvidedDescription == parm) :
                return node
        return None

    def invokeProcessorsOnNodes(self, message: Message) -> bool:
        """Process a message across all nodes

        Args:
            message (Message): Any Message.

        Raises:
            IndexError: If source or destination is wrong (See NodeStore
                or RemoteNodeStore `process` method documentation).

        Returns:
            bool: True if any processor returned True.
        """
        publish = False
        for processor in self.processors :
            for node in self.byIdMap.values() :
                publish = processor.process(message, node) or publish  # always invoke Processor on node first  # noqa: E501
        return publish
