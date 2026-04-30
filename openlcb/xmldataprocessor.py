from collections import OrderedDict
import copy
import os
import xml.sax  # noqa: E402
import xml.sax.handler
import xml.etree.ElementTree as ET

from logging import getLogger
from typing import Callable, List, Tuple, Union
# from xml.sax.xmlreader import AttributesImpl  # for type hints, for autocomplete only in this case  # noqa:E501
import xml.sax.xmlreader  # for type hints, for autocomplete only in this case

from openlcb import d_quote, emit_cast
from openlcb.canbus.canlink import CanLink
from openlcb.cdimemo import CDIMemo, DataProcessorMemo
from openlcb.dataprocessor import DataFormat, DataProcessor
from openlcb.nodeid import NodeID
from openlcb.platformextras import (
    SysDirs,
    clean_file_name,
)
from openlcb.memoryservice import (
    MemoryReadMemo,
    MemorySpace,
)
# from openlcb.remotenodeprocessor import RemoteNodeProcessor
from openlcb.cdivar import (
    CDIVar,
    CLASSNAME_TYPES,
)


if __name__ == "__main__":
    logger = getLogger(__file__)
else:
    logger = getLogger(__name__)


def element_to_dict(element):
    element = ET.Element(element)  # for autocomplete only
    return {
        'tag': element.tag,
        'attrib': element.attrib,  # already dict[str,str]
    }


def attrs_to_dict(attrs) -> dict:
    """Convert parser tag attrs.

    Args:
        attrs (AttributesImpl): attrs from xml parser startElement event
            (Not the same as element.attrib which is already dict).
    """
    # AttributesImpl[str] type hint fails on Python 3.8. For autocomplete:
    # attrs = AttributesImpl(attrs)
    # attrs_dict = attrs.__dict__  # may have private members, so:
    return {key: attrs.getValue(key) for key in attrs.getNames()}


def attrs_to_ordered(attrs: xml.sax.xmlreader.AttributesImpl):
    od = OrderedDict()
    for name in attrs.getNames():
        od['name'] = attrs[name]
    return od


def format_of_space(space, unknown_raises=True):
    assert isinstance(space, MemorySpace)
    if space == MemorySpace.CDI:
        return DataFormat.XML
    elif space == MemorySpace.FDI:
        return DataFormat.XML
    if unknown_raises:
        raise NotImplementedError(emit_cast(space))
    return None


class XMLDataProcessor(xml.sax.handler.ContentHandler, DataProcessor):
    """Collect & process consecutive XML data from each incoming MemoryReadMemo
    - Send events to downloadCDI caller describing the state and content
      of the document construction.
    - Collect and traverse XML in a CDI-specific way.

    Attributes:
        etree (Element): The XML root element (Does not correspond to an
            XML tag but rather the document itself, and contains all
            actual top-level elements as children).
        _openEl (SubElement): Tracks currently-open tag (no `</...>`
            yet) during parsing, or if no tags are open then equals
            etree.
        _ended_memo (CDIMemo|None): The memo most recently popped,
            where "tail" (text after end tag) should be set during
            "characters" when a new tag hasn't been started yet.
            TODO: Put child element's tail in parent (Not part of
            Standard as of 2026-05, but technically possible, such
            as "World" in `<name>Hello<br/>World`).
        _tag_stack (list[SubElement]): Tracks scope during parse since
            self.etree doesn't have awareness of whether end tag is
            finished (and therefore doesn't know which element is the
            parent of a new startElement).
        _data (str): CDI document being collected from the
            network stream (successful read request memo handler). To
            ensure valid state:
            - Initialize to None at program start, end download, or
              failed download.
            - Assert is None at start of download, then set to
              bytearray().
        _space (int): Space containing the CDI itself (not data
            described by CDI).
        _tmp_space (int|None): What space we are currently on
            (of data described by Element(s), not of XML data itself).
        _tmp_address (int|None): For sanity check, not actual address
            (no replication)! See expandedTree docstring.
    """
    XML_TOP_TAGS = ("cdi", "fdi")
    DEFAULT_CACHES_DIR = SysDirs.Cache
    DEFAULT_CACHE_DIR = os.path.join(DEFAULT_CACHES_DIR, "python-openlcb")

    def __init__(self, linkLayer: CanLink, space: MemorySpace):
        self.canLink: CanLink = linkLayer
        # caches_dir = SysDirs.Cache
        self.expanded_root = None  # type: ET.Element|None
        self.expanded_root_memo = None  # type: CDIMemo|None
        self._root_memos = None  # type: list[CDIMemo]|None
        self._root_memo = None  # type: CDIMemo|None
        self._space: Union[MemorySpace, None] = None
        self._openEl: Union[ET.Element, None] = None
        self._top_tag = "cdi"  # cdi or fdi (detected in startElement)
        # self._myCacheDir = os.path.join(caches_dir, "python-openlcb")
        self._ended_memo = None   # type: CDIMemo|None
        self._myCacheDir = XMLDataProcessor.DEFAULT_CACHE_DIR
        self._tmp_space = None  # type: int|None
        self._tmp_address = None  # type: int|None
        assert isinstance(space, MemorySpace)
        self.setSpace(space)  # also sets _format
        # ^ Idle until DataFormat is known
        # ^ In case some parsing step happens early,
        #   prepare these for _callback_msg.
        xml.sax.ContentHandler.__init__(self)
        DataProcessor.__init__(self)
        self.enable_cache = True
        self._stringTerminated = None  # type: Union[bool, None]
        # ^ None means no read is occurring.
        if self._format != DataFormat.XML:
            raise NotImplementedError(
                "This class only handles XML. Make a separate subclass for {}"
                .format(self._format))
        self._parser = xml.sax.make_parser()  # type: xml.sax.xmlreader.XMLReader  # noqa: E501
        self._parser.setContentHandler(self)
        self._data: Union[bytearray, None] = None

        self._realtime = True

        # region ContentHandler
        self._chunks = []
        self._tag_stack = []  # type: List[CDIMemo]
        # endregion ContentHandler
        self.acdi = False

    def getRootMemo(self):
        """Get the root memo object if any.
        This should only be called after the entire file is parsed such
        as when cm.done is True in onStatusMemo(cm) callback. Set
        callback manually if necessary and if using realtime parsing
        (_feed) mode.
        """
        if not self._root_memos:
            return None
        if len(self._root_memos) > 1:
            summaries = []
            cdi_roots = []
            tag = None
            for memo in self._root_memos:
                tag = memo.getTag()
                if tag is not None:
                    tag = tag.lower()
                summaries.append(memo.getTag())
                if tag in ("cdi", "fdi"):
                    cdi_roots.append(memo)
            if len(cdi_roots) == 1:
                return cdi_roots[0]
            if tag not in ("cdi", "fdi"):
                logger.warning(
                    f"Got more than one XML root: {summaries};"
                    " expected cdi/fdi")
            else:
                logger.warning(f"Got more than one XML root: {summaries}")
            return self._root_memos[-1]
        tag = self._root_memos[0].getTag()
        if tag is not None:
            tag = tag.lower()
        if tag not in ("cdi", "fdi"):
            logger.warning(f"Only XML root is {repr(tag)} not cdi/fdi")
        return self._root_memos[0]

    def setSpace(self, space: MemorySpace):
        self._space = space
        self._format = format_of_space(space)

    @property
    def format(self) -> DataFormat:
        assert isinstance(self._format, DataFormat), \
            "expected DataFormat, got {}".format(emit_cast(self._format))
        return self._format

    @property
    def space(self) -> MemorySpace:
        """The memory space of the XML itself. See also
        `space` in event dict in startElement, and _tmp_space."""
        assert isinstance(self._space, MemorySpace)
        return self._space

    def onStatusMemo(self, cm: DataProcessorMemo) -> bool:
        """Handle memo with status that doesn't affect tag stack/scope.
        (Implement in subclass)
        Returns:
            bool: True if handled.
        """
        logger.warning("Default onStatusMemo ran.")
        return False

    def onPushScope(self, cm: CDIMemo) -> bool:
        """Handle memo being added to _tag_stack
        which may already be pushed if a thread is being used
        for download but the UI is on the main thread.
        (Implement in subclass)
        Returns:
            bool: True if handled.
        """
        return False

    def onPopScope(self, cm: CDIMemo) -> bool:
        """Handle memo being popped from _tag_stack
        which may already be popped if a thread is being used
        for download but the UI is on the main thread.
        (Implement in subclass)
        Returns:
            bool: True if handled.
        """
        return False

    def onStartDownload(self):
        """Initialize variables used by element handler(s).
        If subclass is a GUI, reimplement this to reset GUI,
        but also call onStart or super().onStartDownload().
        """
        self._stringTerminated = False
        self._resetTree()
        self.onStart()

    def onStart(self):
        # self._cdi_offset = 0  # Instead see memo.address (which is
        #   incremented on _memoryReadSuccess or custom memory read
        #   handler).
        if self._data is not None:
            raise ValueError(
                "A previous downloadCDI operation is in progress"
                " or failed (Set _data to None first if failed)")
        self._data = bytearray()
        self.progress_count = 0
        self._root_memos = []  # list of roots
        self._root_memo = None

    def onStop(self):
        self._format = DataFormat.EOF  # no data expected

    def _resetTree(self):
        self.etree = ET.Element("root")
        self._openEl = self.etree

    def _fireStatus(self, status,
                    callback: Union[Callable[[CDIMemo], bool], None] = None):
        """Fire status handlers with the given status."""
        if callback is None:
            callback = self.onStatusMemo
        if callback:
            logger.info("OpenLCBNetwork callback_msg({})".format(repr(status)))
            callback(CDIMemo(status=status))
        else:
            logger.warning("No callback, but set status: {}".format(status))

    def _fireStatusMemo(self, statusMemo,
                        callback: Union[Callable[[CDIMemo], bool], None] = None):  # noqa: E501
        """Fire status handlers with the given status."""
        if callback is None:
            callback = self.onStatusMemo
        if callback:
            logger.info(f"OpenLCBNetwork callback_msg({statusMemo})")
            callback(statusMemo)
        else:
            logger.warning(f"No callback, but set status: {statusMemo}")

    def _feedNext(self, memo: MemoryReadMemo):
        """Handle partial CDI XML (any packet except last)
        The last packet is not yet reached, so don't parse (but
        feed if self._realtime, which may trigger a
        callback)

        Args:
            memo (MemoryReadMemo): successful read memo containing data.
        """
        assert self._data is not None
        self._data += memo.data
        self.progress_count = len(self._data)
        partial_str = memo.data.decode("utf-8")
        if self._realtime:
            self._parser.feed(partial_str)  # may call startElement/endElement
        cm = DataProcessorMemo()
        cm.progress_count = self.progress_count
        cm.expected_size = self.expected_size
        self.onStatusMemo(cm)

    def load(self, node_id: NodeID, path, space: Union[MemorySpace, int],
             memo: Union[MemoryReadMemo, None] = None,
             format: Union[DataFormat, None] = None):
        """Load instead of downloading."""
        assert not self._data
        self.onStartDownload()
        assert isinstance(space, (MemorySpace, int))
        if isinstance(space, int):
            try_space = MemorySpace.fromNumber(space)
            if try_space is not None:
                space = try_space
        if isinstance(space, MemorySpace):
            self.setSpace(space)
        else:
            if format is None:
                raise ValueError(f"Using device-specific space: {space}"
                                 " but format not specified")
            else:
                assert isinstance(format, DataFormat)
                self._format = format
                self._space = space  # type:ignore # int if device-specific
                logger.warning(f"Using device-specific space: {space}")
        data = None
        with open(path, "rb") as stream:
            data = stream.read()  # type:ignore
        if self._format is DataFormat.XML:
            if memo is not None:
                assert isinstance(memo, MemoryReadMemo)
            else:
                def memoryReadSuccess(memo: MemoryReadMemo):
                    # See further down
                    print("Fallback memoryReadSuccess ran.")
                    pass

                def memoryReadFail(memo: MemoryReadMemo):
                    raise RuntimeError(
                        "Offline parse failure (should never happen)")

                assert data is not None
                # Based on _startMemoryRead in OpenLCBNetwork:
                memo = MemoryReadMemo(node_id, len(data),
                                      self.getSpaceValue(), 0,
                                      memoryReadFail, memoryReadSuccess)

            assert data is not None
            memo.data = data  # type: ignore
            self._data = bytearray()  # Since _feedLast adds memo.data to it
            memo.size = len(data)
            # based on "else" (done) case in _memoryReadSuccess
            #   in OpenLCBNetwork:
            self._stringTerminated = True
            self._feedLast(memo, enable_cache=False)
            self.onStop()  # sets self._format to DataFormat.EOF
        else:
            logger.warning(f"Custom DataFormat {self._format}"
                           f" (space={space}): not parsed automatically.")

    def getSpaceValue(self):
        # type: () -> int|None
        if self._space is None:
            return None
        if isinstance(self._space, MemorySpace):
            return self._space.value
        assert isinstance(self._space, int)
        return self._space

    def _feedLast(self, memo: MemoryReadMemo, enable_cache=None):
        """Handle end of CDI XML (last packet)
        End of data, so parse (or feed if self._realtime)

        Args:
            memo (MemoryReadMemo): successful read memo containing data.
            enable_cache (bool): Defaults to self.enable_cache.
        """
        if enable_cache is None:
            enable_cache = self.enable_cache
        partial_str = memo.data.decode("utf-8")
        # save content
        assert self._data is not None
        self._data += memo.data
        # concert resultingCDI to a string up to 1st zero
        # and process that
        cdiString = None
        if self._realtime:
            # If _realtime, last chunk is treated same as another
            #   (since _realtime uses feed) except stop at '\0'.
            null_i = memo.data.find(b'\0')
            terminate_i = len(memo.data)
            if null_i > -1:
                terminate_i = min(null_i, terminate_i)
            partial_str = memo.data[:terminate_i].decode("utf-8")
            assert self.progress_count is not None
            self.progress_count += terminate_i
            cm = DataProcessorMemo()
            cm.done = True  # 'done' and not 'error' means got all
            cm.progress_count = self.progress_count
            cm.expected_size = self.expected_size
            self.onStatusMemo(cm)
        else:
            # *not* realtime (but got to end, so parse all at once)
            cdiString = ""
            null_i = self._data.find(b'\0')
            terminate_i = len(self._data)
            if null_i > -1:
                terminate_i = min(null_i, terminate_i)
            cdiString = self._data[:terminate_i].decode("utf-8")
            assert self.progress_count is not None
            self.progress_count += terminate_i

            # print (cdiString)
            # self.parse(cdiString)  # no such method
            # self._parser.parse(cdiString)  # urllib.error.URLError
            # ^ startElement, endElement, etc. all consecutive using parse
            # ^ urllib.error.URLError: <urlopen error unknown url type:
            #   ?xml version="1.0" encoding="utf-8"?>
            xml.sax.parseString(cdiString, self)
            # self._fireStatus("Done loading CDI.")
            cm = DataProcessorMemo()
            cm.done = True  # 'done' and not 'error' means got all
            cm.progress_count = self.progress_count
            self.onStatusMemo(cm)
        if self._realtime:
            self._parser.feed(partial_str)  # may call startElement/endElement
        # memo = MemoryReadMemo(memo)
        path = self.cacheFilePath(memo.nodeID)
        with open(path, 'w') as stream:
            if cdiString is None:
                cdiString = self._data.rstrip(b'\0').decode("utf-8")
            stream.write(cdiString)
            print('Saved {}'.format(repr(path)))
        self._data = None  # Ensure isn't reused for more than one doc

    def cacheFilePathCustom(self, item_id: Union[NodeID, str], **kwargs):
        if 'my_cache_dir' not in kwargs:
            kwargs['my_cache_dir'] = self._myCacheDir
        type(self).cacheFilePath(item_id, **kwargs)

    @classmethod
    def cacheFileName(cls, item_id: Union[NodeID, str], ext=".cdi.xml"):
        item_id = str(item_id)  # Convert NodeID or other
        clean_name = clean_file_name(item_id.replace(":", "."))
        clean_name += ext
        return clean_name

    @classmethod
    def cacheFilePath(cls, item_id: Union[NodeID, str], my_cache_dir=None,
                      subfolder: Union[str, None] = "cdi", name=None,
                      ext=".cdi.xml"):
        if my_cache_dir is None:
            my_cache_dir = cls.DEFAULT_CACHE_DIR
        if subfolder:
            cdi_cache_dir = os.path.join(my_cache_dir, subfolder)
        else:
            cdi_cache_dir = my_cache_dir
        if not os.path.isdir(cdi_cache_dir):
            os.makedirs(cdi_cache_dir)
        # TODO: add hardware name and firmware version and from SNIP to
        #   name file to avoid cache file from a different
        #   device/version.
        if not name:
            clean_name = cls.cacheFileName(item_id, ext=ext)
        else:
            clean_name = clean_file_name(name)
            if clean_name != name:
                logger.warning(
                    "[cacheFilePath]"
                    f" changed name {repr(name)} to {repr(clean_name)}")
        # ^ replace ":" to avoid converting that one to default "_"
        # ^ will raise error if path instead of name
        path = os.path.join(cdi_cache_dir, clean_name)
        if path == clean_name:
            # just to be safe, even though clean_file_name
            #   should prevent. If this occurs, fix clean_file_name.
            raise ValueError("Cannot specify absolute path.")
        return path

    def startElement(self, name: str,
                     attrs: xml.sax.xmlreader.AttributesImpl):
        """See xml.sax.handler.ContentHandler documentation."""
        tab = "  " * len(self._tag_stack)
        if name is not None:
            if name.lower() in ("cdi", "fdi"):
                self._top_tag = name.lower()
            elif name.lower() == "acdi":
                self.acdi = True
        content = self._flushCharBuffer() if self._chunks else None
        if content is not None:
            if self._ended_memo is not None:
                self._ended_memo.tail = content
            else:
                if self._tag_stack:
                    # Text in parent before this
                    #   (typically "\n", possibly indentation).
                    if self._tag_stack[-1].content is None:
                        self._tag_stack[-1].content = content
                    else:
                        self._tag_stack[-1].content += content
                else:
                    logger.warning(
                        f"Stray characters before {repr(name)}: {repr(content)}")
        if self._ended_memo is not None:
            self._ended_memo = None
        attrib = attrs_to_dict(attrs)
        origin = attrib.get('origin')
        offset = attrib.get('offset')
        parts = [tab, "Start: ", name]
        if origin is not None:
            parts.append(f"origin={origin}")
        if offset is not None:
            parts.append(f"offset={offset}")
        logger.debug(*parts)
        if (attrs is not None) and attrs.getNames():
            logger.debug(tab, "  Attributes: ", attrs.getNames())
        # el = ET.Element(name, attrs)

        # NOTE: self._openEl is root if this is the first tag.
        assert self._openEl is not None, "_openEl wasn't even set to etree yet"

        el = ET.SubElement(self._openEl, name, attrib)
        parent_cm = None
        if self._tag_stack:
            parent_cm = self._tag_stack[-1]
        cm = CDIMemo(tag=name, element=el, parent=parent_cm, document=self)
        if name == "segment":
            self._tmp_space = attrib.get('space')
            self._tmp_address = int(attrib.get('origin', 0))
            if self._tmp_space is None:
                raise AttributeError("Node didn't specify space for segment")
            else:
                self._tmp_space = int(self._tmp_space)
        else:
            offset = attrib.get('offset')
            if offset is not None:
                offset = int(offset)
                if self._tmp_address is None:
                    raise AttributeError(
                        f"Node specifies {name} offset before segment origin")
                self._tmp_address += offset
                # NOTE: ^ Sanity check only! For real address see expandedTree.

        self.onPushScope(cm)
        if len(self._tag_stack) < 1:
            assert self._root_memos is not None, "onStart must run first"
            self._root_memos.append(cm)
            if cm.tag == "cdi":
                self._root_memo = cm

        # self._callback_msg(
        #     "loaded: {}{}".format(tab, ET.tostring(el, encoding="unicode")))
        self._tag_stack.append(cm)
        self._openEl = el
        size = attrib.get('size')
        if size is not None:
            if name == "segment":
                logger.warning("Node segment should not specify size.")
            if self._tmp_address is None:
                raise AttributeError(
                    f"Node has {name} variable before segment origin")
            self._tmp_address += int(size)

    def checkDone(self, cm: CDIMemo):
        """Notify the caller if parsing is over.
        Calls self.onStatusMemo with `'done': True` in the argument if
        'name' is "cdi" or the detected self._top_tag
        (case-insensitive). That notifies the downloadCDI caller that
        parsing is over, so that caller should end progress bar/other
        status tracking for downloadCDI in that case.

        Returns:
            CDIMemo: Reserved for synchronous use.
        """
        cm.done = False
        if not cm.tag or cm.tag.lower() != self._top_tag:
            # Not </cdi> nor other detected self._top_tag, so not done
            return cm
        cm.done = True  # done: past conditional return above
        self.onStatusMemo(cm)
        return cm

    def endElement(self, name: str):
        """See xml.sax.handler.ContentHandler documentation.
        Called on end tag or after startElement on self-closing tag.
        """
        indent = len(self._tag_stack)
        tab = "  " * indent
        # top_cm = self._tag_stack.pop()  # raises index error if empty
        top_cm = self._tag_stack[-1] if len(self._tag_stack) else None
        top_el = top_cm.element if top_cm is not None else None
        if top_el is None:
            pass  # see warning case further down
        elif name != top_el.tag:
            pass  # see warning case further down
        elif indent > 0:  # top element found and indent not 0
            indent -= 1  # dedent since scope ended
        # print(tab, name, "content:", self._flushCharBuffer())
        logger.debug(tab, "End: ", name)
        if name == "segment":
            self._tmp_space = None
            self._tmp_address = None
        cm = None
        if top_cm is not None:
            top_cm.tag = name
            cm = top_cm
        else:
            cm = CDIMemo(tag=name, document=self)
            cm.stray = True
        cm.end = True

        if not self._tag_stack:
            cm.error = "</{}> before any start tag".format(name)
            print(tab+"Warning: {}".format(cm.error))
            self.checkDone(cm)
            return
        if (top_el is None):
            cm.error = "stray </{}> before top element".format(name)
            print(tab+"Warning: {}".format(cm.error))
            self.checkDone(cm)
            return
        elif name != top_el.tag:
            cm.error = (
                "</{}> before top tag <{} ...> closed"
                .format(name, top_el.tag if top_el else None))
            print(tab+"Warning: {}".format(cm.error))
            self.checkDone(cm)
            return
        del self._tag_stack[-1]
        if self._tag_stack:
            self._openEl = self._tag_stack[-1].element
        else:
            self._openEl = self.etree
        if len(self._tag_stack) and cm.stray:
            cm.parent = self._tag_stack[-1]
            cm.element = top_el
        # else parent & element should already have been set in startElement
        if cm.parent is not None:
            cm.parent.children.append(cm)
        _ = self.checkDone(cm)
        cm.content = self._flushCharBuffer()
        self._ended_memo = cm
        self.onPopScope(cm)

    def _flushCharBuffer(self):
        """Decode the buffer, clear it, and return all content.
        See xml.sax.handler.ContentHandler documentation.
        - Use this in endElement so that the callback gets all content.

        Returns:
            str: The content of the bytes buffer decoded as utf-8.
        """
        s = ''.join(self._chunks)
        self._chunks.clear()
        return s

    def characters(self, content: str):
        """Received characters handler.
        See xml.sax.handler.ContentHandler documentation.

        Args:
            content (str): any content (between tags)
        """
        # Union[bytearray, bytes, List[int]]
        if not isinstance(content, str):
            raise TypeError(
                "Expected str, got {}".format(type(content).__name__))
        self._chunks.append(content)

    def expandedTree(self) -> Tuple[CDIMemo, ET.Element]:
        """Build an expanded XML tree with replication and addresses.

        Starting from the root CDIMemo (via :meth:`getRootMemo`), this
        method creates a new ElementTree. Replication is expanded,
        addresses are calculated per the OpenLCB CDI standard, and
        ``address`` attributes are added where required.

        The ``replication`` attribute is removed from all copied group
        elements in the new tree. The original tree is left unchanged.

        Returns:
            ET.Element: Root of the new expanded tree.
        """
        root_memo = self.getRootMemo()
        assert root_memo is not None and root_memo.element is not None

        new_root = ET.Element("cdi")  # always new: children added from memos
        new_root.attrib.update(root_memo.element.attrib)

        new_root_memo = copy.deepcopy(root_memo)  # deepcopy to edit children!
        new_root_memo.document = self
        size = self._expanded_tree_recursive(new_root_memo, new_root, address=0)
        if size < 1:
            logger.warning(f"No space used by CDI after replication (size={size})")
        return new_root_memo, new_root

    def _expanded_tree_recursive(
        self, parent: CDIMemo, parent_el: ET.Element,
        allow_non_standard=False,
        address: int = 0,
        space: Union[int, None] = None,
    ) -> int:
        """Recursive helper for :meth:`expandedTree`.

        Copies the element, handles replication, sets addresses, and
        recurses into children. Removes ``replication`` attribute from
        copied group elements.
        """
        assert address is not None
        assert parent.element is not None
        parent_tag = parent.getTag() or parent.element.tag
        parent_tag_lower = parent_tag.lower()
        if parent_el.text:
            parent.content = parent_el.text
        elif parent.content:  # new_root
            parent_el.text = parent.content
        elif parent_tag_lower in ("name", "description"):
            logger.warning(
                f"expanded {parent_tag_lower} has no content.")
        if parent_el.tail:
            parent.tail = parent_el.tail
        elif parent.tail:  # new_root
            parent_el.tail = parent.tail

        # Recurse into children (replication handled at this level)
        new_children = []
        # new_child_elements = []
        for child_memo in parent.children:
            replication_str = parent.element.attrib.get('replication')
            count = int(replication_str) if replication_str is not None else 1
            child_tag = child_memo.getTag()
            assert child_tag
            c_tag_lower = child_tag.lower()
            child_el = child_memo.element
            assert child_el is not None
            if c_tag_lower == "segment":
                space_str = child_el.attrib.get('space')
                assert space_str, "expected space in segment"
                space = int(space_str)
                origin = child_el.attrib.get('origin')
                address = int(origin) if (origin is not None) else 0
            if c_tag_lower == "group":
                offset = child_el.attrib.get('offset')
                if offset:
                    address += int(offset)
            for idx in range(count):
                # if count > 1:
                copy_child_el = ET.Element(child_el.tag)
                copy_child_el.attrib.update(child_el.attrib)
                copy_child_el.text = child_el.text
                if child_el.text is not None:
                    copy_child_el.text = child_el.text.strip()
                copy_child_el.tail = child_el.tail
                if child_el.tail is not None:
                    copy_child_el.tail = child_el.tail.strip()
                copy_child_memo = copy.deepcopy(child_memo)
                copy_child_memo.parent = parent
                copy_child_memo.document = self
                copy_child_memo.element = copy_child_el
                # else:
                #     copy_child_el = child_el
                #     copy_child_memo = child_memo
                # NOTE: ^ Why commented: We don't want to modify
                #   self.etree children (if we modify expandedTree
                #   result such as self.expanded_root)!
                #   - Don't even chance it by keeping the memo
                #     (otherwise child_memo.element would be from tree).
                #   - Also, we always add child to parent_el below.

                new_children.append(copy_child_memo)
                # for child_el in new_parent:
                #     copy_parent_el.append(child_el)

                # Remove replication from the expanded copy
                if "replication" in copy_child_el.attrib:
                    del copy_child_el.attrib["replication"]

                if c_tag_lower == "group" or c_tag_lower in CLASSNAME_TYPES:
                    copy_child_el.set('address', str(address))
                    copy_child_el.set('space', str(space))
                    if c_tag_lower in CLASSNAME_TYPES:
                        copy_child_memo.address = address
                        copy_child_memo.space = space

                    if replication_str is not None:
                        if c_tag_lower != "group":
                            el_error = \
                                f"unexpected replication for {c_tag_lower} tag"
                            if allow_non_standard:
                                logger.warning(el_error)
                            else:
                                raise SyntaxError(el_error)
                        copy_child_el.set('replication_index', str(idx))
                        # ^ optimized attrib[key] = value

                parent_el.append(copy_child_el)
                # parent: Use new_children below (can't change while iterating)

                # Determine size for address advancement
                if c_tag_lower == "eventid":
                    size = 8
                elif "size" in copy_child_el.attrib:
                    size = int(copy_child_el.attrib["size"])
                else:
                    size = 0

                # Advance address *before* leaf variables
                if size:
                    if c_tag_lower in CLASSNAME_TYPES:
                        assert size, f"expected size for {c_tag_lower}"
                        address += size
                    else:
                        el_error = (
                            f"size is not expected for {c_tag_lower}"
                            f" size={size}")
                        if allow_non_standard:
                            logger.warning(el_error)
                            address += size
                        else:
                            assert not size, el_error

                address = self._expanded_tree_recursive(
                    copy_child_memo, copy_child_el, address=address,
                    space=space)
                if c_tag_lower == "segment":
                    space = None  # undefined after section

        parent.children = new_children  # Same references if no replication
        return address

    def extractCDIVarMemos(self, expanded_root=None, root_memo=None) -> List[CDIMemo]:  # noqa: E501
        # type: (ET.Element|None, CDIMemo|None) -> List[CDIMemo]
        """Build a flat list of CDIMemo objects for all variables.

        Uses the expanded tree (replication expanded, replication
        attribute removed, addresses set). Returns original-style
        memos (with .content) but with .element pointing into the
        expanded tree so that modifications (setData etc.) affect
        the saved XML.
        """
        # TODO: Implement ACDI vars if present (See OpenLCB
        #     "Configuration Description Information" Standard)
        if not hasattr(self, "etree") or self.etree is None:
            logger.error("processor has no etree")
            return []
        if expanded_root is not None:
            if root_memo is not None:  # reserved
                assert isinstance(root_memo, CDIMemo)
            assert isinstance(expanded_root, ET.Element)
            root_memo = root_memo  # reserved
            root_el = expanded_root
        else:
            root_memo, root_el = self.expandedTree()
        self.expanded_root = root_el
        self.expanded_root_memo = root_memo

        assert isinstance(self.expanded_root_memo, CDIMemo)

        cdivar_memos: List[CDIMemo] = []

        def traverse(memo: CDIMemo) -> None:
            tag = memo.getTag()
            tag_lower = tag.lower() if tag else ""
            if tag_lower in CLASSNAME_TYPES:
                # Use the existing expanded memo (has correct .content)
                cdivar_memos.append(memo)
            for child in memo.children:
                traverse(child)

        traverse(self.expanded_root_memo)
        assert root_el is self.expanded_root  # concurrent modification check
        return cdivar_memos
