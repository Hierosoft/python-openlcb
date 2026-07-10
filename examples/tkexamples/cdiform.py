"""
CDI Frame

A reusable widget for editing LCC node settings as described by the
node's Configuration Description Information (CDI).

This file is part of the python-openlcb project
(<https://github.com/bobjacobsen/python-openlcb>).

Contributors: Poikilos
"""
from functools import partial
import logging
import os
import sys
import tkinter as tk
import warnings

from tkinter import EventType, ttk

from collections import deque
from logging import getLogger
from typing import Any, Callable, Dict, List, Union
from xml.etree import ElementTree as ET

from openlcb.cdivar import CLASSNAME_TYPES, CDIVar
from openlcb.memoryservice import MemoryReadMemo, MemoryWriteMemo
from openlcb.nodeid import NodeID
from openlcb.openlcbnetwork import OpenLCBNetwork


if __name__ == "__main__":
    logger = getLogger(__file__)
else:
    logger = getLogger(__name__)

TKEXAMPLES_DIR = os.path.dirname(os.path.realpath(__file__))
EXAMPLES_DIR = os.path.dirname(TKEXAMPLES_DIR)
REPO_DIR = os.path.dirname(EXAMPLES_DIR)
if os.path.isfile(os.path.join(REPO_DIR, "openlcb", "__init__.py")):
    sys.path.insert(0, REPO_DIR)
else:
    logger.warning(
        "Reverting to installed copy if present (or imports will fail),"
        " since test running from repo but could not find openlcb in {}."
        .format(repr(REPO_DIR)))
try:
    from openlcb.xmldataprocessor import XMLDataProcessor
    from openlcb.cdimemo import CDIMemo
    from openlcb.linklayer import LinkLayer
    from openlcb.memoryspace import MemorySpace
    from openlcb.xmldataprocessor import element_to_dict
except ImportError as ex:
    print("{}: {}".format(type(ex).__name__, ex), file=sys.stderr)
    print("* You must run this from a venv that has openlcb installed"
          " or adds it to sys.path like examples_settings does.",
          file=sys.stderr)
    raise  # sys.exit(1)


class CDIForm(ttk.Frame, XMLDataProcessor):
    """A GUI frame to represent the CDI visually as a tree.

    Attributes:
        enableRepDump (bool): Print XML to console while
            performing replication. Replication is done in this class
            rather than calling replicatedTree, so that widgets can be
            generated in real time (while downloading XML).
            In general, using replicatedTree is easier.

    Args:
        parent (TkWidget): Typically a ttk.Frame or tk.Frame with "root"
            attribute set.
        linkLayer (LinkLayer): Typically a CanLink instance.
    """
    def __init__(self, *args, **kwargs):
        assert issubclass(type(args[1]), LinkLayer), \
            "Expected LinkLayer/subclass got {}".format(type(args[0]).__name__)
        linkLayer = args[1]
        assert issubclass(type(args[0]), tk.Widget)
        XMLDataProcessor.__init__(self, linkLayer, MemorySpace.CDI)
        ttk.Frame.__init__(self, *args[:1], **kwargs)
        self._top_widgets = []
        if len(args) < 1:
            raise ValueError("at least one argument (parent) is required")
        self.parent = args[0]
        self.mainform = args[2]
        self.root = args[2]
        assert hasattr(self.mainform, 'network'), \
            "mainform must have 'network' OpenLCBNetwork"
        assert hasattr(self.mainform, 'settings'), \
            "mainform must have 'settings' dictionary with at least 'farNodeID'"
        self._status_callback = None
        if hasattr(self.parent, 'root'):
            self.root = self.parent.root
        elif hasattr(self.mainform, 'root'):
            self.root = self.mainform.root
        self._container = self  # where to put visible widgets
        self._treeview = None  # type: ttk.Treeview|None
        self._treeMemos = {}  # type: Dict[str, CDIMemo]

        self._gui(self._container)
        self.cursorCol = 0

        self.cdiSettingWidgets = []  # type: list[tk.Widget]
        self.cdiSettingRow = 0
        self.cdiSettingFrame = None  # type: Union[ttk.Frame, tk.Frame, None]
        assert not hasattr(self, 'address'), "using redundant variable"
        self._parsing_address = None
        self._scope = []  # type: list[CDIMemo]
        self.multilineTags = ["segment", "group"]
        self.multilineTags += list(CLASSNAME_TYPES.keys())
        self.multilineTags += ["map", "relation"]
        self.enableRepDump = False

    def scopeIndent(self, tab="    ") -> str:
        """Get indent for debug lines
        for showing tag scope visually (as indentation) during parsing.
        """
        return tab * len(self._scope)

    def scopeTags(self, show_attrib=True) -> List[str]:
        """Get debug info regarding XML stack
        (current parsing scope). It is empty after document is finished.
        """
        items = []
        for cm in self._scope:
            tagRepr = cm.tag
            if show_attrib:
                assert cm.tag is not None
                tagRepr = "<" + cm.tag
                if cm.element is not None:
                    for k, v in cm.element.attrib.items():
                        tagRepr += f' {k}="{v}"'
                tagRepr += ">"
            items.append(tagRepr)
        return items

    def getScopeIdx(self, tag):
        tag = tag.lower()
        for idx in reversed(range(len(self._scope))):
            cm = self._scope[idx]
            assert cm.tag is not None
            if cm.tag.lower() == tag:
                return idx
        return -1

    def getScope(self, tag):
        idx = self.getScopeIdx(tag)
        if idx < 0:
            return None
        return self._scope[idx]

    def setSettingsContainer(self, container: Union[ttk.Frame, tk.Frame]):
        self.cdiSettingFrame = container

    def _gui(self, container: tk.Widget):
        if self._top_widgets:
            raise RuntimeError("gui can only be called once unless reset")
        self._status_var = tk.StringVar(self)
        self._status_label = ttk.Label(container,
                                       textvariable=self._status_var)
        self._status_label.grid(sticky=tk.NSEW, row=len(self._top_widgets))
        self._top_widgets.append(self._status_label)
        self._overview = ttk.Frame(container)
        self._overview.grid(sticky=tk.NSEW, row=len(self._top_widgets))
        self._top_widgets.append(self._overview)
        self._treeview = ttk.Treeview(container)
        self._treeview.grid(sticky=tk.NSEW, row=len(self._top_widgets))
        self._treeview.bind("<<TreeviewSelect>>", self.onTreeSelect)
        self.rowconfigure(len(self._top_widgets), weight=1)  # weight=1: expand
        self._top_widgets.append(self._treeview)
        self._current_iid = 0   # id of Treeview element

    def onTreeSelect(self, event: tk.Event):
        # print(f"event={event}")
        # print(f"dir(event)={dir(event)}")
        # print(f"event.__dict__={event.__dict__}")
        # ^ {'serial': 794, 'num': '??', 'height': '??', 'keycode':
        #   '??', 'state': 0, 'time': 0, 'width': '??', 'x': 0, 'y': 0,
        #   'char': '??', 'send_event': False, 'keysym': '??',
        #   'keysym_num': '??', 'type': <EventType.VirtualEvent: '35'>,
        #   'widget': <tkinter.ttk.Treeview object
        #   .!mainform.!notebook.!frame.!cdiform.!treeview>, 'x_root':
        #   0, 'y_root': 0, 'delta': 0}
        for iid in event.widget.selection():
            item = event.widget.item(iid)  # type: dict
            # ^ such as {'text': 'Track Output', 'image': '',
            #   'values': [CDIMemo], 'open': 0, 'tags': ''}
            cm = self._treeMemos[iid]
            # print(f"type(item)={type(item)}")
            # raise NotImplementedError(item)
            print(f"cm={cm}")
            self.clearSettingWidgets()
            if cm.tag not in CLASSNAME_TYPES:
                # Non-value (such as segment or group)
                #   So there is nothing to do.
                return

            name = cm.getChildContent("name")
            if name is None:
                # self.setStatus("Selected element has no name.")
                break

            nameLabel = ttk.Label(self.cdiSettingFrame, text=name)
            nameLabel.tip = cm.getChildContent("description")
            nameLabel.grid(column=0, row=self.cdiSettingRow)
            self.cdiSettingWidgets.append(nameLabel)
            # self.cdiSettingRow += 1
            cdivar = cm.toCDIVar()
            tkvar = None
            v_widget = None
            mapToValue = cm.valueMap()
            # self.mapToValue = mapToValue
            if mapToValue:
                tkvar = tk.StringVar(self.root)
                v_widget = ttk.Combobox(self.cdiSettingFrame,
                                        textvariable=tkvar,
                                        values=list(mapToValue.keys()))
                v_widget.mapToValue = mapToValue
            elif cdivar.max:
                if cdivar.className == "int":
                    tkvar = tk.IntVar(self.root)
                elif cdivar.className == "float":
                    tkvar = tk.DoubleVar(self.root)
                else:
                    raise TypeError("Device should not specify max for {}"
                                    .format(cdivar.className))
                v_widget = ttk.LabeledScale(self.cdiSettingFrame,
                                            variable=tkvar,
                                            from_=cdivar.min,
                                            to=cdivar.max)
                # ^ widget.scale is ttk.Scale, widget.label is ttk.Label
                # ^ a.k.a. Slider (if not using Tk)
                v_widget.scale.cdivar = cdivar
                v_widget.scale.tip = nameLabel.tip

                def update_label_width(*args):
                    # Fix label being too small to show value:
                    v_widget.label.configure(width=len(str(int(tkvar.get()))) + 2)  # noqa: E501
                tkvar.trace_add('write', update_label_width)
            else:
                tkvar = tk.StringVar(self.root)
                v_widget = ttk.Entry(self.cdiSettingFrame, textvariable=tkvar)
            v_widget.grid(column=1, row=self.cdiSettingRow)
            self.cdiSettingRow += 1
            self.cdiSettingWidgets.append(v_widget)
            if cdivar.default is not None:
                defaultStr = cdivar.default
                if mapToValue:
                    mapToStr = cm.keyMap()
                    assert mapToStr
                    defaultStr = mapToStr[str(cdivar.default.value())]
                tkvar.set(defaultStr)
            v_widget.cdivar = cdivar
            v_widget.tip = nameLabel.tip
            try:
                if hasattr(v_widget, 'scale'):
                    v_widget.scale.configure(state=tk.DISABLED)
                else:
                    v_widget.configure(state="readonly")  # readonly until refresh
                if hasattr(v_widget, 'label'):
                    v_widget.label.configure(state=tk.DISABLED)
            except tk.TclError:
                pass  # N/A such as for Scale
            #   so that previous value is known.

            # Write and Read buttons
            writeButton = ttk.Button(
                self.cdiSettingFrame,
                text="Write",
                command=partial(self.onWriteValueClicked, v_widget, tkvar,
                                cdivar, mapToValue=mapToValue),
            )
            writeButton.grid(column=0, row=self.cdiSettingRow)

            readButton = ttk.Button(
                self.cdiSettingFrame,
                text="Read",
                command=partial(self.onReadValueClicked, v_widget, tkvar,
                                cdivar, mapToValue=mapToValue),
            )
            readButton.grid(column=1, row=self.cdiSettingRow)
            self.cdiSettingRow += 1

            # Show the address
            address_str = ""
            if address_str is not None:
                address_str = str(cm.address)
            a_widget = ttk.Label(self.cdiSettingFrame, text="(Address:")
            a_widget.grid(column=0, row=self.cdiSettingRow, sticky=tk.W)
            av_widget = ttk.Label(self.cdiSettingFrame, text=address_str + ")")
            av_widget.grid(column=1, row=self.cdiSettingRow)
            self.cdiSettingWidgets.append(a_widget)
            self.cdiSettingWidgets.append(av_widget)
            self.cdiSettingRow += 1
            break

    def onReadValueClicked(self, v_widget: tk.Widget,
                           tkvar: Union[tk.StringVar, tk.IntVar, tk.DoubleVar],
                           cdivar: CDIVar, mapToValue=None):
        print("read:"
              f" space={cdivar.space}={hex(cdivar.space)}"
              f" address={cdivar.address}={hex(cdivar.address)}"
              f" size={cdivar.size}={hex(cdivar.size)}")
        # read 64 bytes from the CDI space starting at address zero
        assert hasattr(self.mainform, 'settings'), \
            "mainform must have 'settings' dictionary"
        assert 'farNodeID' in self.mainform.settings, \
            "mainform 'settings' dictionary is missing 'farNodeID'"
        farNodeIDStr = self.mainform.settings['farNodeID']

        memMemo = MemoryReadMemo(NodeID(farNodeIDStr),
                                 cdivar.size, cdivar.space,
                                 cdivar.address, self.memoryReadFail,
                                 self.memoryReadSuccess)
        memMemo.widget = v_widget
        memMemo.tkvar = tkvar
        memMemo.cdivar = cdivar
        memMemo.mapToValue = mapToValue
        network = self.mainform.network  # type: OpenLCBNetwork
        self.setStatus("Memory read...")
        network._memoryService.requestMemoryRead(memMemo)

    def memoryReadFail(self, memo: MemoryReadMemo):
        self.setStatus("Memory read...error.")

    def memoryReadSuccess(self, memo: MemoryReadMemo):
        self.setStatus("Memory read...success.")
        widget = None  # type: tk.Widget | None
        tkvar = None  # type: tk.StringVar | tk.IntVar | tk.DoubleVar | None
        cdivar = None  # type: CDIVar | None
        if hasattr(memo, 'widget'):
            widget = memo.widget
            try:
                # widget['state'] = tk.NORMAL
                if hasattr(widget, 'scale'):
                    widget.scale.configure(state=tk.NORMAL)
                else:
                    widget.configure(state=tk.NORMAL)  # readonly until refresh
                if hasattr(widget, 'label'):
                    widget.label.configure(state=tk.NORMAL)
            except tk.TclError:
                pass  # N/A (such as Scale)
        value = None
        mapToValue = None
        found = None
        if hasattr(memo, 'cdivar'):
            cdivar = memo.cdivar
            assert cdivar is not None
            cdivar.setData(memo.data)
            value = cdivar.value()
            if (value is not None) and hasattr(memo, 'mapToValue'):
                mapToValue = memo.mapToValue
                if mapToValue:
                    for k, v in mapToValue.items():
                        # if str(v.value()) == str(value):
                        if v.value() == value:
                            value = k  # key is the user-facing string
                            found = value
                            break
                    if found is None:
                        logger.warning(
                            f"Found no matching value for {repr(value)}"
                            f" in {mapToValue}")
                    else:
                        logger.warning(
                            f"Found matching value {repr(value)} for {found}")
                else:
                    logger.debug(
                        f"There is no value map. Using {repr(value)} directly")
            else:
                logger.debug(
                    f"There is no value map. Using {repr(value)} directly")
        else:
            logger.warning("There is no cdivar.")
        if hasattr(memo, 'tkvar'):
            tkvar = memo.tkvar
            if value is not None:
                if isinstance(tkvar, tk.StringVar):
                    print(f"Set StringVar to {repr(value)}")
                    tkvar.set(str(value))
                else:
                    print(f"Set {type(tkvar).__name__} to {repr(value)}"
                          f" ({cdivar.data})")
                    # Assume input already matches type of tk var
                    tkvar.set(value)

    def onWriteValueClicked(self, v_widget: tk.Widget,
                            tkvar: Union[tk.StringVar, tk.IntVar, tk.DoubleVar],  # noqa: E501
                            cdivar: CDIVar, mapToValue=None):
        print(f"write: {cdivar.className}({repr(tkvar.get())})"
              f" space={cdivar.space}={hex(cdivar.space)}"
              f" address={cdivar.address}={hex(cdivar.address)}"
              f" size={cdivar.size}={hex(cdivar.size)}")
        # read 64 bytes from the CDI space starting at address zero
        assert hasattr(self.mainform, 'settings'), \
            "mainform must have 'settings' dictionary"
        assert 'farNodeID' in self.mainform.settings, \
            "mainform 'settings' dictionary is missing 'farNodeID'"
        farNodeIDStr = self.mainform.settings['farNodeID']
        cdivar.setFromString(tkvar.get())
        memMemo = MemoryWriteMemo(NodeID(farNodeIDStr),
                                  self.memoryWriteSuccess,
                                  self.memoryWriteFail,
                                  cdivar.size, cdivar.space,
                                  cdivar.address, cdivar.getData())
        memMemo.widget = v_widget
        memMemo.tkvar = tkvar
        memMemo.cdivar = cdivar
        memMemo.mapToValue = mapToValue
        network = self.mainform.network  # type: OpenLCBNetwork
        self.setStatus("Memory write...")
        network._memoryService.requestMemoryWrite(memMemo)

    def memoryWriteSuccess(self, memo):
        self.setStatus("Memory write...success.")

    def memoryWriteFail(self, memo):
        self.setStatus("Memory write...failed.")

    def clearSettingWidgets(self):
        for widget in self.cdiSettingWidgets:
            widget.grid_forget()
            widget.destroy()
        del self.cdiSettingWidgets[:]
        self.cdiSettingRow = 0

    def clear(self):
        while self._top_widgets:
            widget = self._top_widgets.pop()
            widget.grid_forget()
        self._gui(self._container)
        self.setStatus("Display reset.")

    # def connect(self, new_socket, localNodeID, callback=None):
    #     return OpenLCBNetwork.connect(self, new_socket, localNodeID,
    #                                   callback=callback)

    def indent(self):
        return len(self._tag_stack) * "  "

    def setStatus(self, text: str):
        # See also MainForm
        if self._status_callback:
            self._status_var.set("")
            self._status_callback(text)
            return
        self._status_var.set(text)

    def setStatusCallback(self, callback: Callable):
        self._status_callback = callback

    def getStatus(self):
        # See also MainForm
        return self._status_var.get()

    def onStartDownload(self):
        """Initialize variables used by element handler(s)."""
        XMLDataProcessor.onStartDownload(self)
        # TODO: clear tree?

    def onStatusMemo(self, cm: CDIMemo) -> bool:
        """Handler for incoming CDI tag
        Use this for callback in downloadCDI
        (onStatusMemo replaces _dataProcessor's _onElement
        formerly set by downloadCDI).

        Args:
            cm (CDIMemo): Document parsing state info
        """
        show_status = None
        if cm.error:
            show_status = cm.error
        elif cm.status:
            show_status = cm.status
        elif cm.done:
            show_status = "Done loading CDI."
        if show_status:
            self.root.after_idle(self.setStatus, show_status)
        if cm.done:
            return True
        return False

    def onPushScope(self, cm: CDIMemo,
                    replication_index: Union[int, None] = None) -> bool:
        if self.enableRepDump:
            if cm.tag not in self.multilineTags:
                sys.stdout.write(self.scopeIndent() + cm.toXMLStart())
            else:
                print(self.scopeIndent() + cm.toXMLStart())
        if self._scope:
            if cm.parent is not self._scope[-1]:
                old = self._scope[-1]
                old_name = old.getChildContent('name')
                new_name = cm.parent.getChildContent('name')
                old_idx = old.element.attrib.get('replicated_index')
                new_idx = cm.parent.element.attrib.get('replicated_index')
                logger.info(
                    "expected same parent"
                    # f" {CDIMemo.to_dict(cm.parent, trim_blank=True)},"
                    f" {old.tag} name={old_name} idx={old_idx}"
                    f" got other parent {cm.parent.tag} name={new_name}"
                    f" idx={new_idx},")
        if replication_index is not None:
            cm.element.attrib['replication_index'] = str(replication_index)
        self._scope.append(cm)
        if cm.element is None:
            raise ValueError("No element for push tag event")
        # Parse in realtime to prevent out-of-order processing
        #   potentially caused by the UI framework's "after" method.
        offset = cm.element.attrib.get('offset')
        if offset is not None:
            offset = int(offset)
            assert self._parsing_address is not None, \
                f"{cm.tag} offset before segment!"
            self._parsing_address += offset

        # NOTE: _onPushScope (not onPushScope) is on main thread which
        #   is the only thread that can affect the GUI.
        if cm.tag == "segment":
            if self.getScope("group") is not None:
                raise RuntimeError(
                    "Tried to parse segment start before group end"
                    " (or less likely, XML is non-standard"
                    " having segment in group)")
            self._parsing_space = int(cm.element.attrib['space'])
            origin = cm.element.attrib.get('origin')
            if origin is None:
                origin = 0
                logger.debug(f"Defaulting segment to origin={origin}")
            self._parsing_address = int(origin)
        elif cm.tag == "group":
            assert self._parsing_address is not None, \
                f"{cm.tag} before segment!"
            # replication: See onPopScope (after entire size is known)
        elif cm.tag in CLASSNAME_TYPES:
            assert self._parsing_address is not None, \
                f"{cm.tag} before segment!"
            cm.space = self._parsing_space
            cm.address = self._parsing_address
            # NOTE: ^ This becomes the real address since onPopScope
            #   performs replication and calls onPushScope again for
            #   each (excluding first) copy.
            varSize = cm.getSize()
            assert varSize is not None, f"expected size for {cm.tag}"
            varSize = int(varSize)
            self._parsing_address += varSize
        self.root.after_idle(self._onPushScope, cm)
        self.onStatusMemo(cm)
        return True

    def recursiveParse(self, cm: CDIMemo,
                      replication_index: Union[int, None] = None):
        """Push a non-XML (generated) memo, simulating recursive parsing
        """
        self.onPushScope(cm, replication_index=replication_index)
        for child in cm.children:
            child.parent = cm
            self.recursiveParse(child, replication_index=replication_index)
        self.onPopScope(cm)

    def onPopScope(self, cm: CDIMemo) -> bool:
        if cm.tag != self._scope[-1].tag:
            space = None
            origin = None
            if cm.element is not None:
                space = cm.element.get('space')
                origin = cm.element.get('origin')
            logger.warning(
                f"Popping </{cm.tag}> (space={space} origin={origin})"
                f" before </{self._scope[-1].tag}>"
                f" (stack: {self.scopeTags()})")
        topMemo = self._scope.pop()
        assert topMemo is not None
        assert cm is topMemo, \
            f"Got {cm.toXMLStart()} different than top {topMemo.toXMLStart()}"
        content = ""
        # Content isn't collected until end tag.
        if (cm.element is not None) and (cm.element.text is not None):
            content = cm.element.text
        elif cm.content is not None:
            content = cm.content
        if self.enableRepDump:
            sys.stdout.write(content)
            if cm.tag not in self.multilineTags:
                print(cm.toXMLEnd())  # use print even for single line tag
                #  since this is the end of the element.
            else:
                print(self.scopeIndent() + cm.toXMLEnd())
        if cm.element is None:
            raise ValueError("No element for pop tag event")
        # memos = [cm]
        replication = cm.element.attrib.get('replication')
        if replication is not None:
            # Replication must be during onPopScope since children
            #   weren't processed until now.
            replication = int(replication)
            for i in range(replication):
                if i == 0:
                    # else onPushScope was already called for [0] (original)
                    # cm.element.attrib['replication_index'] = str(i)
                    self.root.after_idle(self._onPopScope, cm)
                    continue
                replicatedMemo = cm.copy()
                replicatedMemo.iid = None  # Not in tree yet
                #   (See _treeview.insert in onPushScope)
                # Delete replication to prevent infinite replication:
                assert replicatedMemo.element is not None
                del replicatedMemo.element.attrib['replication']
                replicatedMemo.element.attrib['replication_index'] = str(i)
                # memos.append(replicatedMemo)
                self.recursiveParse(
                    replicatedMemo,
                    replication_index=i
                )
                # self.onPushScope(replicatedMemo, replication_index=i)
                # if replicatedMemo.children:
                #     assert len(replicatedMemo.children) == len(cm.children)
                #     for cI, child in enumerate(replicatedMemo.children):
                #         child.parent = replicatedMemo
                #         assert (len(child.children)
                #                 == len(cm.children[cI].children))
                #         self.recursiveParse(child, replication_index=i)
                # self.onPopScope(replicatedMemo)
            self.onStatusMemo(cm)
            return True

        self.root.after_idle(self._onPopScope, cm)
        self.onStatusMemo(cm)
        return True

    def getParentBranch(self, cm: CDIMemo) -> str:
        """Get the Treeview branch iid of the tag currently being parsed"""
        # if not len(self._tag_stack):
        #     return ""
        # branch = self._tag_stack[-1].getBranch()
        # NOTE: ^ _tag_stack is unreliable due to race condition
        #   (append/pop may occur before or after this call)!
        branch = cm.getBranch()
        return branch if (branch is not None) else ""

    def _onPopScope(self, cm: CDIMemo):
        """Handle end XML tag processed by XMLDataProcessor's superclass
        (accesses GUI, so must run on main thread)

        Args:
            cm (CDIMemo): XML element container from
                `startElement` or endElement in XMLDataProcessor
                superclass
                - 'element' (xml.etree.ElementTree.Element): Any Element
                - 'content' (str): Content (only set during this
                  callback, not start tag).

        """
        if self.cursorCol != 0:
            self.debug()
        nameLower = cm.tag.lower() if cm.tag else None
        assert nameLower is not None  # only None for done/fail events
        cm.content
        assert self._treeview is not None
        if nameLower in ("name", "repname"):
            parentIID = self.getParentBranch(cm)  # source is cm.parent.iid
            #   where parent is also a CDIMemo (if parent is None, then cm.iid
            #   or "" to place at top level of tree)
            assert parentIID is not None, "name must be in a branch"
            content = cm.content
            if nameLower == "repname":
                if content is not None:
                    content = content.strip()
                else:
                    content = ""
                assert cm.parent is not None
                assert cm.parent.element is not None
                idx = cm.parent.element.attrib.get('replication_index')
                if idx is not None:
                    idx = int(idx)
                    content += f" #{idx+1}"
            if parentIID:
                # assert content is not None
                if cm.content is None:
                    logger.warning(
                        self.indent() + f"content is None for /{cm.tag}")
                    cm.content = ""
                    content = ""
                if nameLower == "repname":
                    nameItem = self._treeview.item(parentIID)
                    if nameItem:
                        content = f"{nameItem['text']}: {content}"
                # "name" applies to parent, such as "segment" or "string"
                if content is not None:
                    _ = self._treeview.item(parentIID, text=content)
            origin = cm.element.attrib.get('origin') if cm.element else None
            if cm.content:
                if cm.tag == "segment":
                    # ^ Should be set (since element start tag's CDIMemo
                    #   should be reused for end)
                    self.debug(f'/{cm.tag} origin="{origin}" "{cm.content}"')
                else:
                    self.debug('/{} "{}"'.format(cm.tag, cm.content))
            else:
                parts = [f"/{cm.tag}"]
                if cm.element:
                    origin = cm.element.attrib.get('origin')
                    offset = cm.element.attrib.get('offset')
                    if origin is not None:
                        parts.append(f'origin="{origin}"')
                    if offset is not None:
                        parts.append(f'offset="{offset}"')
                self.debug(*parts)
        else:
            parts = [f"/{cm.tag}"]
            if cm.element:
                origin = cm.element.attrib.get('origin')
                offset = cm.element.attrib.get('offset')
                if origin is not None:
                    parts.append(f'origin="{origin}"')
                if offset is not None:
                    parts.append(f'offset="{offset}"')
            self.debug(*parts)
            logger.debug(self.indent() + "Done ignoring {}".format(cm.tag))
        if cm.iid:
            # If in tree, check if it is an empty group (no name so remove it).
            children = self._treeview.get_children(cm.iid)
            if (cm.getTag() == "group") and (not children):
                # self._treeview.detach(cm.iid)  # remove but don't destroy
                self._treeview.delete(cm.iid)  # detach and destroy
        return cm

    def write(self, *args, **kwargs):
        args = list(args)
        if self.cursorCol == 0:
            tab = len(self._tag_stack)*"  "
            self.cursorCol += len(tab)
            args.insert(0, tab)  # prepend indent
        for arg in args:
            sys.stdout.write(arg)
            self.cursorCol += len(arg)
            sys.stdout.flush()

    def debug_write(self, *args, **kwargs):
        if logger.level < logging.DEBUG:
            return
        self.write(*args, **kwargs)

    def print(self, *args, **kwargs):
        if self.cursorCol == 0:  # No indent yet, so use write.
            self.write(*args, **kwargs)
            print()
        else:
            print(*args, **kwargs)
        self.cursorCol = 0

    def debug(self, *args, **kwargs):
        kwargs['file'] = sys.stderr
        if logger.level < logging.DEBUG:
            return
        self.print(*args, **kwargs)

    def _onPushScope(self, cm: CDIMemo):
        """Handle start XML tag processed by XMLDataProcessor's superclass
        (accesses GUI, so must run on main thread)

        Args:
            cm (CDIMemo): XML element container from
                `startElement` or endElement in XMLDataProcessor
                superclass
                - 'element' (xml.etree.ElementTree.Element): Any Element
                - 'space' (str, optional): MemorySpace value as string.
                  Only optional for identification and its children,
                  otherwise required (collected from ancestors by
                  XMLDataProcessor)
                - 'address' (str, optional): Memory address. Only
                  optional for identification and its children otherwise
                  required (previous start tags by XMLDataProcessor)

        """
        # NOTE: If it is self-closing such as
        #   `<group offset='4'/>`,
        #   then onPopScope will run next (via endElement such
        #   as in python-openlcb's implementation of ContentHandler).
        assert cm.element is not None
        tag = cm.element.tag if cm.element is not None else None
        if not tag:
            logger.warning("Ignored blank tag for event: {}".format(cm))
            return
        tagLower = tag.lower()
        index = "end"  # "end" is at end of current branch (otherwise use int)
        name = cm.element.tag
        if self.cursorCol != 0:
            self.debug()
        self.debug_write(name)
        # if attrs is not None and attrs:
        #     self.debug(" {}".format(attrs_to_dict(attrs)))
        assert self._treeview is not None
        if tagLower in ("segment", "group"):
            content = ""  # Temporary (The visible text is set to content of
            #   name element in _onPopScope)
            # if not name:
            if tagLower == "segment":
                space = cm.element.attrib['space']
                content = space
                # origin = None
                # if 'origin' in cm.element.attrib:
                #     origin = cm.element.attrib['origin']
            elif tagLower == "group":
                if 'offset' in cm.element.attrib:
                    content = cm.element.attrib['offset']
                # else must be a subgroup (offset optional in that case)
            else:
                raise NotImplementedError(tagLower)
            new_branch = self._treeview.insert(
                self.getParentBranch(cm),
                index,
                iid=self._current_iid,
                text=content,
            )
            self._treeMemos[new_branch] = cm
            # values=(), image=None
            # self._tag_stack[-1].iid = new_branch
            # NOTE: ^ _tag_stack is unreliable due to race condition!
            cm.iid = new_branch
            self._current_iid += 1  # TODO: associate with SubElement
        elif tagLower == "acdi":
            pass  # handled by superclass (sets self.acdi)
        elif tagLower in CLASSNAME_TYPES:
            content = ""  # NOTE: name sub-tag isn't parsed yet.
            new_branch = self._treeview.insert(
                self.getParentBranch(cm),
                index,
                iid=self._current_iid,
                text=content,
            )
            self._treeMemos[new_branch] = cm
            # values=(), image=None
            # self._tag_stack[-1].iid = new_branch
            # NOTE: ^ _tag_stack is unreliable due to race condition!
            cm.iid = new_branch
            self._current_iid += 1  # TODO: associate with SubElement
            #  and/or set values keyword argument to create association(s)
        # NOTE: Can't get content of any tag such as name until onPopScope


if __name__ == "__main__":
    warnings.warn("You tried to run a module"
                  " (Run your main script or import this instead).")
