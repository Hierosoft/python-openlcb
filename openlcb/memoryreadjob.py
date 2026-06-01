from logging import getLogger
from typing import Callable, Union
import xml.sax

from openlcb.canbus.canlink import CanLink
from openlcb.convert import Convert
from openlcb.dataprocessor import DataFormat
from openlcb.dataprocessormemo import DataProcessorMemo
from openlcb.memoryservice import MemoryReadMemo
from openlcb.memoryspace import MemorySpace
from openlcb.nodeid import NodeID

logger = getLogger(__name__)


class MemoryReadJob:
    """Reusable multi-chunk memory read job.
    Callbacks get results of memory read
    (override in subclass for specific behavior such as progress).
    """
    def __init__(self, memoryService, ):
        self.memoryService = memoryService
        # accumulate the CDI information
        self.resultingCDI = bytearray()
        self.handler = None
        self.dataFormat = None
        self.completeData = False
        self.failed = False
        self.memMemo = None
        self.statusCallback = None

    def readMemory(self, canLink, farNodeID: NodeID,
                   space: Union[int, MemorySpace],
                   dataFormat: Union[DataFormat, None] = None, handler=None,
                   callback: Union[Callable[[DataProcessorMemo], None], None] = None):  # noqa: E501
        """Create and send a read datagram.
        This is a read of 20 bytes from the start of CDI space. We will
        fire it on a separate thread to give time for other nodes to
        reply to AME.
        """
        memo = DataProcessorMemo()
        self.handler = handler
        if dataFormat is None:
            if isinstance(space, int):
                spaceID = MemorySpace.fromNumber(space)
            else:
                assert isinstance(space, MemorySpace)
                spaceID = space
            if spaceID in (MemorySpace.CDI, MemorySpace.FDI):
                dataFormat = DataFormat.XML
        assert isinstance(dataFormat, DataFormat)
        if dataFormat is DataFormat.XML:
            assert handler is not None, \
                "XML needs handler (xml.sax.handler.ContentHandler/subclass)"
        self.dataFormat = dataFormat
        self.statusCallback = callback

        def echoS(message: str):
            """push a message"""
            memo.status = message
            if callback is not None:
                callback(memo)

        if isinstance(space, MemorySpace):
            space = space.value
        echoS("")
        echoS(f"Requesting memory read (space={space}). Please wait...")
        # read 64 bytes from the CDI space starting at address zero
        self.memMemo = MemoryReadMemo(farNodeID, 64, space, 0,
                                      self.memoryReadFail,
                                      self.memoryReadSuccess)
        self.memoryService.requestMemoryRead(self.memMemo)

    def memoryReadSuccess(self, memo):
        """Handle a successful read
        Invoked when the memory read successfully returns,
        this queues a new read until the entire CDI has been
        returned.  At that point, it invokes the XML processing below.

        Args:
            memo (MemoryReadMemo): Successful MemoryReadMemo
        """
        # print("successful memory read: {}".format(memo.data))

        # is this done?
        if len(memo.data) == 64 and 0 not in memo.data:
            # save content
            self.resultingCDI += memo.data
            logger.info(
                f"[{memo.address}] successful read"
                f" `{Convert.arrayToString(memo.data, len(memo.data))}`"
                "; next = address + 64")
            # update the address
            memo.address = memo.address+64
            # and read again
            self.memoryService.requestMemoryRead(memo)
            # The last packet is not yet reached, so don't parse (However,
            #   parser.feed could be called for realtime processing).
        else :
            # and we're done!
            # save content
            self.resultingCDI += memo.data
            # concert resultingCDI to a string up to 1st zero
            cdiString = ""
            null_i = self.resultingCDI.find(b'\0')
            terminate_i = len(self.resultingCDI)
            if null_i > -1:
                terminate_i = min(null_i, terminate_i)
            cdiString = self.resultingCDI[:terminate_i].decode("utf-8")
            # print (cdiString)

            # and process that
            if self.dataFormat is DataFormat.XML:
                self.processXML(cdiString)
            else:
                print(
                    f"Skipping processing for misc. format: {self.dataFormat}")
            self.completeData = True
            memo = DataProcessorMemo()
            memo.status = ""
            memo.done = True
            # done

    def memoryReadFail(self, memo: MemoryReadMemo):
        assert isinstance(memo, MemoryReadMemo)
        print(f"memory read failed: id={memo.nodeID}"
              f" data={memo.data} space={memo.space} address={memo.address}"
              f" error={memo.error} code={memo.errorCode}")
        self.failed = True

    def processXML(self, content: str) :
        """process the XML and invoke callbacks

        Args:
            content (str): Raw XML data
        """
        # NOTE: The data is complete in this example since processXML is
        #   only called when there is a null terminator, which indicates the
        #   last packet was reached for the requested read.
        #   - See memoryReadSuccess comments for details.
        with open("cached-cdi.xml", 'w') as stream:
            # NOTE: Actual caching should key by all SNIP info that could
            #   affect CDI/FDI: manufacturer, model, and version. Without
            #   all 3 being present in SNIP, the cache may be incorrect.
            stream.write(content)
        assert self.handler is not None, \
            "XML needs handler (xml.sax.handler.ContentHandler/subclass)"
        xml.sax.parseString(content, self.handler)
        print("\nParser done")
