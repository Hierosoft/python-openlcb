import os

from logging import getLogger
from typing import Union
from openlcb import emit_cast
from openlcb.storagepool import StoragePool
from openlcb.node import PIP, SNIP, Node

from openlcb.localnodeprocessor import LocalNodeProcessor
from openlcb.nodeid import (
    NodeID,
)
from openlcb.xmldataprocessor import (
    CanLink,
    CDIMemo,
    CDIVar,
    # CLASSNAME_TYPES,
    d_quote,
    MemoryReadMemo,
    MemorySpace,
    XMLDataProcessor,
)

logger = getLogger(__name__)


class LocalNode(Node, StoragePool):
    """A Node with its own virtual memory
    (emulate memory spaces such as for creating a virtual
    signal node with settings)"""
    def __init__(self, id: NodeID, snip: SNIP, pipSet: set,
                 linkLayer: CanLink):
        Node.__init__(self, id, snip, pipSet)
        StoragePool.__init__(self)
        self.cdi = None  # type: XMLDataProcessor|None
        self._replicated_cdi_tree = None  # type: CDIMemo|None
        if PIP.CONFIGURATION_DESCRIPTION_INFORMATION in pipSet:
            self.cdi = XMLDataProcessor(linkLayer, MemorySpace.CDI)
        else:
            logger.warning(
                "PIP.CONFIGURATION_DESCRIPTION_INFORMATION is not in pipSet"
                f" for new LocalNode {self.cdi}, so XMLDataProcessor"
                " will not be initialized (functioning as Node, unless"
                " remote user knows addresses apart from CDI)")
        self.localNodeProcessor = LocalNodeProcessor(linkLayer, self)
        linkLayer.registerMessageReceivedListener(
            self.localNodeProcessor.process)

    def loadCDIFile(self, path, memo=None):
        """Load a CDI file to generate virtual memory spaces
        (to create a virtual node, not representing a remote one)

        Args:
            path (str): Location of original file, also used
                to generate cache dir (parent of path).
            memo (MemoryReadMemo): Typically left blank,
                This would provide a success or fail message,
                but this method can be called asynchronously
                since LocalNode assumes local data is loaded,
                not network data.
        """
        assert isinstance(path, str)
        if not os.path.isfile(path):
            raise FileNotFoundError(path)

        # self.cdi.load(self.id, path, MemorySpace.CDI, memo)
        xml_data = None
        with open(path, "wb") as stream:
            xml_data = stream.read()
        return self.loadCDIString(xml_data, path, memo=memo)

    def loadCDIString(self, xml_data, path, memo=None):
        """Load raw XML data from a string.
        Args:
            xml_data (Union[bytes, bytearray, str]): Raw XML
            path (str): Location of original file, for
                reference and use as cache dir (parent of path).
            memo (Optional[MemoryReadMemo]): Typically left blank,
                This would provide a success or fail message,
                but this method can be called asynchronously
                since LocalNode assumes local data is loaded,
                not network data.
        """
        self.cdiBackupDir = os.path.dirname(path)
        assert self.cdi is not None, \
            ("PIP.CONFIGURATION_DESCRIPTION_INFORMATION is not in pipSet"
             f" for LocalNode {self.id}")
        if memo is None:
            memo = MemoryReadMemo(
                self.id, 0, MemorySpace.CDI.value, 0,
                self.onCDILoadFailed, self.onCDILoaded)
        self.cdi.load(self.id, path, MemorySpace.CDI, memo, data=xml_data)
        # with open(path, "r") as stream:
        #     data = stream.read()
        #     self.tree = etree.fromstring(data)
        self.reserveSpaces()

    def setMemory(self, memo: CDIMemo, var: CDIVar):
        """Set a memory address at memo to the value in var"""
        assert memo.space is not None
        size = memo.getSize()
        assert size is not None
        assert size > 0, f"size={repr(size)}"
        assert memo.address is not None
        # if var is None:
        #     var = memo.toCDIVar()
        assert var is not None
        assert var.data is not None
        assert len(var.data) == memo.getSize()
        self.set(memo.space, memo.address, var.data)
        print(f"Set LocalNode {self.id} space {memo.space}"
              f" address {memo.space} (length {len(var.data)}).")

    def reserveSpaces(self, parent: Union[CDIMemo, None] = None):

        assert self.cdi is not None, \
            ("PIP.CONFIGURATION_DESCRIPTION_INFORMATION is not in pipSet"
             f" for LocalNode {self.id}")

        if parent is None:
            parent = self.cdi.getRootMemo()
        assert parent is not None
        assert parent.tag == "cdi", f"Expected cdi, got {parent.tag}"
        assert parent.element is not None
        if (('replicated' in parent.element.attrib)
                and (parent.element.attrib['replicated'] == "true")):
            # Caller already used replicatedTree
            return self._reserveSpaces(parent=parent)
        replicated_root_memo, replicated_root = self.cdi.replicatedTree()
        self.cdi.replicated_root_memo = replicated_root_memo
        self.cdi.replicated_root = replicated_root
        # ^ self.cdi.replicated_root_memo can also be set via
        #   self.cdi.extractCDIVarMemos.
        return self._reserveSpaces(
            parent=self.cdi.replicated_root_memo,
        )

    def _reserveSpaces(self, parent: Union[CDIMemo, None] = None, level=0):
        assert parent is not None
        assert parent.tag is not None
        tag = parent.tag.lower()
        if tag == "cdi":
            assert parent.element is not None
            assert parent.element.attrib['replicated'] == "true", \
                "replicated_root_memo accounting for replication must be used."
        if tag in ("int", "float"):  # CLASSNAME_TYPES:
            # cast_fn = int if tag == "int" else float
            var = parent.toCDIVar()
            # _min = parent.getChildContentN("min", tag)
            # _max = parent.getChildContentN("max", tag)
            value = parent.getChildContentN("default", tag)
            # size = parent.getSize()
            # assert size is not None
            # var = CDIVar(parent.tag, _min=_min, _max=_max, _size=size)
            if value is not None:
                if tag == "float":
                    var.setFloat(value)
                elif tag == "int":
                    assert isinstance(value, int), \
                        f"tried to use {emit_cast(value)} for int tag"
                    var.setInt(value)
                assert var.data is not None
                # var.default = bytearray(copy.deepcopy(var.data))
                assert parent.space is not None, \
                    f"No space defined in CDI for a(n) {tag}"
                self.setMemory(parent, var)
            return
        for child in parent.children:
            self._reserveSpaces(child, level=level+1)
        if level == 0:
            if not self.cdiBackupDir:
                logger.warning(
                    f"Not backing up virtual node {self.id} memory since"
                    " no cdiBackupDir is set for the LocalNode instance.")
                return
            if not os.path.isdir(self.cdiBackupDir):
                logger.warning(
                    f"Creating cdiBackupDir {self.cdiBackupDir}")
                os.makedirs(self.cdiBackupDir)
            for space, data in self.spaces.items():
                name = f"{self.id}.lcc-link-virtual-node.space={space}.xml"
                path = os.path.join(self.cdiBackupDir, name)
                with open(path, "wb") as stream:
                    stream.write(data)
                    print(f"Wrote {d_quote(path)}")

    def onCDILoaded(self, memo: MemoryReadMemo):
        """Default handler, typically enough since CDI is local
        in the case of LocalNode"""
        assert self.cdi is not None, \
            ("PIP.CONFIGURATION_DESCRIPTION_INFORMATION is not in pipSet"
             f" for LocalNode {self.id}")
        print(f"LocalNode onFileLoaded {self.cdi.getPath()}: {memo}")

    def onCDILoadFailed(self, memo: MemoryReadMemo):
        """Default handler for file load failed.
        Shouldn't happen unless application has provided malformed XML,
        since CDI is local in the case of LocalNode
        """
        assert self.cdi is not None, \
            ("PIP.CONFIGURATION_DESCRIPTION_INFORMATION is not in pipSet"
             f" for LocalNode {self.id}")
        print(f"LocalNode onCDILoadFailed {self.cdi.getPath()}: {memo}")
