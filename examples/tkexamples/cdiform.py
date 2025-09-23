"""
CDI Frame

A reusable widget for editing LCC node settings as described by the
node's Configuration Description Information (CDI).

This file is part of the python-openlcb project
(<https://github.com/bobjacobsen/python-openlcb>).

Contributors: Poikilos
"""
import os
import sys
import tkinter as tk
from tkinter import ttk

from collections import deque
from logging import getLogger
from typing import Callable

from openlcb.linklayer import LinkLayer
from openlcb.memoryservice import MemorySpace
from openlcb.metadataprocessor import element_to_dict
# from xml.etree import ElementTree as ET


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
    from openlcb.metadataprocessor import XMLDataProcessor
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
        self.ignore_non_gui_tags = None
        if hasattr(self.parent, 'root'):
            self.root = self.parent.root
        self._container = self  # where to put visible widgets
        self._treeview = None
        self._gui(self._container)

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
        self.rowconfigure(len(self._top_widgets), weight=1)  # weight=1: expand
        self._top_widgets.append(self._treeview)
        self._populating_stack = None  # no parent when top of Treeview
        self._current_iid = 0   # id of Treeview element

    def clear(self):
        while self._top_widgets:
            widget = self._top_widgets.pop()
            widget.grid_forget()
        self._gui()
        self.setStatus("Display reset.")

    # def connect(self, new_socket, localNodeID, callback=None):
    #     return OpenLCBNetwork.connect(self, new_socket, localNodeID,
    #                                   callback=callback)

    def setStatus(self, message: str):
        # See also MainForm
        self._status_var.set(message)

    def getStatus(self):
        # See also MainForm
        return self._status_var.get()

    def onStartDownload(self):
        """Initialize variables used by element handler(s)."""
        self.onStart()
        self._resetTree()
        self.ignore_non_gui_tags = deque()
        self._populating_stack = deque()

    def on_cdi_element(self, event_d: dict):
        """Handler for incoming CDI tag
        Use this for callback in downloadCDI, which sets parser
        (_dataProcessor)'s _onElement.

        Args:
            event_d (dict): Document parsing state info:
                - 'element' (SubElement): The element
                  that has been completely parsed ('</...>' reached)
                - 'error' (str): Message of failure (requires 'done' if
                  stopped).
                - 'done' (bool): If True, downloadCDI is finished.
                  Though document itself may be incomplete if 'error' is
                  also set, stop tracking status of downloadCDI
                  regardless.
                - 'end' (bool): False to start a deeper scope, or True
                  for end tag, which exits current scope (last created
                  Treeview branch in this case, or top if empty
                  self._populating_stack).
        """
        done = event_d.get('done')
        error = event_d.get('error')
        status = event_d.get('status')
        element = event_d.get('element')
        if element is None:
            raise ValueError("No element for tag event")
        show_status = None
        if error:
            show_status = error
        elif status:
            show_status = status
        elif done:
            show_status = "Done loading CDI."
        if show_status:
            self.root.after(0, self.setStatus, show_status)
        if done:
            return
        if event_d.get('end'):
            self.root.after(0, self._on_cdi_element_end, event_d)
        else:
            self.root.after(0, self._on_cdi_element_start, event_d)

    def _on_cdi_element_end(self, event_d: dict):
        name = event_d['name']
        nameLower = name.lower()
        if (self.ignore_non_gui_tags
                and (nameLower == self.ignore_non_gui_tags[-1])):
            print("Done ignoring {}".format(name))
            self.ignore_non_gui_tags.pop()
            return
        if not self._populating_stack:
            element = event_d.get('element')
            if nameLower in ("acdi", "cdi"):
                raise ValueError(
                    "Can't close acdi, is self-closing (no branch pushed)")
            tag = None
            element_d = None
            if element is not None:
                tag = element.tag  # same as name in startElement
                element_d = element_to_dict(element)
            logger.error("Unexpected element_d={}".format(element_d))
            raise IndexError(
                "Got stray end tag in top level of XML (event_d={},"
                " name={}, element_d={}, ignore_non_gui_tags={})"
                .format(event_d, tag, element_d,
                        self.ignore_non_gui_tags))
            # pop would also raise IndexError, but this message is more clear.
        return self._populating_stack.pop()

    def _populating_branch(self):
        if not self._populating_stack:
            return ""  # "" (empty str) is magic value for top of ttk.Treeview
        return self._populating_stack.pop()

    def _on_cdi_element_start(self, event_d: dict):
        element = event_d.get('element')
        segment = event_d.get('segment')
        groups = event_d.get('groups')
        prev_ignore_size = len(self.ignore_non_gui_tags)
        tag = element.tag
        if not tag:
            logger.warning("Ignored blank tag for event: {}".format(event_d))
            return
        tagLower = tag.lower()
        # TODO: handle start tags separately (Branches are too late to be
        #   created here since all children are done).
        index = "end"  # "end" is at end of current branch (otherwise use int)
        prev_stack_size = len(self._populating_stack)
        if tagLower in ("segment", "group"):
            name = ""
            for child in element:
                if child.tag.lower() == "name":
                    name = child.text
                    # FIXME: move to end tag when done populating
                    break
            # element = ET.Element(element)  # for autocomplete only
            # if not name:
            if tagLower == "segment":
                space = element.attrib['space']
                name = space
                origin = None
                if 'origin' in element.attrib:
                    origin = element.attrib['origin']
            elif tagLower == "group":
                if 'offset' in element.attrib:
                    name = element.attrib['offset']
                # else must be a subgroup (offset optional in that case)
            else:
                raise NotImplementedError(tagLower)

            # ^ 'xml.etree.ElementTree.Element' object has no attribute 'attrs'
            new_branch = self._treeview.insert(
                self._populating_branch(),
                index,
                iid=self._current_iid,
                text=name,
            )
            self._populating_stack.append(new_branch)
            # values=(), image=None
            self._current_iid += 1  # TODO: associate with SubElement
        elif tagLower == "acdi":
            # "Indicates that certain configuration information in the
            # node has a standardized simplified format."
            # Configuration Description Information - Standard - section 5.1
            # (self-closing tag; triggers startElement and endElement)
            self.ignore_non_gui_tags.append(tagLower)
        elif tagLower in ("int", "string", "float"):
            name = ""
            for child in element:
                if child.tag == "name":
                    name = child.text
                    break
            new_branch = self._treeview.insert(
                self._populating_branch(),
                index,
                iid=self._current_iid,
                text=name,
            )
            self._populating_stack.append(new_branch)
            # values=(), image=None
            self._current_iid += 1  # TODO: associate with SubElement
            #  and/or set values keyword argument to create association(s)
        elif tagLower == "cdi":
            self.ignore_non_gui_tags.append(tagLower)
        else:
            logger.warning("Ignored {}".format(tag))
            self.ignore_non_gui_tags.append(tagLower)

        if len(self.ignore_non_gui_tags) <= prev_ignore_size:
            if len(self._populating_stack) <= prev_stack_size:
                raise NotImplementedError(
                    "Must either ignore tag (to prevent pop"
                    " during _on_cdi_element_end)"
                    " or add to GUI stack so end tag can pop {}"
                    .format(tagLower))
