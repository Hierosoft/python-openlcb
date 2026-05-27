"""
CDI Frame

A reusable widget for editing LCC node settings as described by the
node's Configuration Description Information (CDI).

This file is part of the python-openlcb project
(<https://github.com/bobjacobsen/python-openlcb>).

Contributors: Poikilos
"""
import logging
import os
import sys
import tkinter as tk
import warnings

from tkinter import EventType, ttk

from collections import deque
from logging import getLogger
from typing import Any, Callable, Dict, Union
from xml.etree import ElementTree as ET

from openlcb.cdivar import CLASSNAME_TYPES, CDIVar


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

    Args:
        parent (TkWidget): Typically a ttk.Frame or tk.Frame with "root"
            attribute set.
    """
    def __init__(self, *args, **kwargs):
        assert isinstance(args[0], LinkLayer), \
            "Expected LinkLayer/subclass got {}".format(type(args[0]).__name__)
        linkLayer = args[0]
        args = args[1:]  # remove first argument (only for GUI)
        XMLDataProcessor.__init__(self, linkLayer, MemorySpace.CDI)
        ttk.Frame.__init__(self, *args, **kwargs)
        self._top_widgets = []
        if len(args) < 1:
            raise ValueError("at least one argument (parent) is required")
        self.parent = args[0]
        self.root = args[0]
        self._status_callback = None
        if hasattr(self.parent, 'root'):
            self.root = self.parent.root
        self._container = self  # where to put visible widgets
        self._treeview = None  # type: ttk.Treeview|None
        self._treeMemos = {}  # type: Dict[str, CDIMemo]

        self._gui(self._container)
        self.cursorCol = 0

        self.cdiSettingWidgets = []  # type: list[tk.Widget]
        self.cdiSettingRow = 0
        self.cdiSettingFrame = None  # type: Union[ttk.Frame, tk.Frame, None]

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
            # print(f"cm={cm}")
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
            if cdivar.max:
                if cdivar.className == "int":
                    tkvar = tk.IntVar(self.root)
                elif cdivar.className == "float":
                    tkvar = tk.DoubleVar(self.root)
                else:
                    raise TypeError("Device should not specify max for {}"
                                    .format(cdivar.className))

                v_widget = ttk.LabeledScale(self.cdiSettingFrame, variable=tkvar)
                # ^ widget.scale is ttk.Scale, widget.label is ttk.Label
                v_widget.scale.cdivar = cdivar
                v_widget.scale.tip = nameLabel.tip
            else:
                tkvar = tk.StringVar(self.root)
                v_widget = ttk.Entry(self.cdiSettingFrame, textvariable=tkvar)
            v_widget.grid(column=1, row=self.cdiSettingRow)
            self.cdiSettingRow += 1
            self.cdiSettingWidgets.append(v_widget)
            if cdivar.default is not None:
                tkvar.set(cdivar.default)
            v_widget.cdivar = cdivar
            v_widget.tip = nameLabel.tip

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

    def setStatus(self, message: str):
        # See also MainForm
        if self._status_callback:
            self._status_var.set("")
            self._status_callback(message)
            return
        self._status_var.set(message)

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
            self.root.after(0, self.setStatus, show_status)
        if cm.done:
            return True
        return False

    def onPushScope(self, cm: CDIMemo) -> bool:
        if cm.element is None:
            raise ValueError("No element for push tag event")
        self.root.after(0, self._onPushScope, cm)
        self.onStatusMemo(cm)
        return True

    def onPopScope(self, cm: CDIMemo) -> bool:
        if cm.element is None:
            raise ValueError("No element for pop tag event")
        self.root.after(0, self._onPopScope, cm)
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

        Raises:
            NotImplementedError: _description_
            NotImplementedError: _description_
        """
        if self.cursorCol != 0:
            self.debug()
        nameLower = cm.tag.lower() if cm.tag else None
        assert nameLower is not None  # only None for done/fail events
        cm.content
        assert self._treeview is not None
        if nameLower == "name":
            parentIID = self.getParentBranch(cm)
            assert parentIID is not None, "name must be in a branch"
            if parentIID:
                assert cm.content is not None
                cm.content = cm.content.strip()
                if cm.content is None:
                    logger.warning(
                        self.indent() + f"content is None for /{cm.tag}")
                    cm.content = ""
                # "name" applies to parent, such as "segment" or "string"
                _ = self._treeview.item(
                    parentIID, text=cm.content.strip())
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

        Raises:
            NotImplementedError: _description_
            NotImplementedError: _description_
        """
        # NOTE: If it is self-closing such as
        #   `<group offset='4'/>`,
        #   then _onPopScope will also run (see endElement such
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
        elif tagLower in ("int", "string", "float"):
            content = ""
            for child in cm.element:
                if child.tag == "name":
                    content = child.text
                    if content is None:
                        content = ""
                    break
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


if __name__ == "__main__":
    warnings.warn("You tried to run a module"
                  " (Run your main script or import this instead).")
