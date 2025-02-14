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

from logging import getLogger



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
    from openlcb.cdihandler import CDIHandler
except ImportError as ex:
    print("{}: {}".format(type(ex).__name__, ex), file=sys.stderr)
    print("* You must run this from a venv that has openlcb installed"
          " or adds it to sys.path like examples_settings does.",
          file=sys.stderr)
    raise  # sys.exit(1)


import xml.sax  # noqa: E402

class CDIForm(ttk.Frame, CDIHandler):
    """A GUI frame to represent the CDI visually as a tree.

    Args:
        parent (TkWidget): Typically a ttk.Frame or tk.Frame with "root"
            attribute set.
    """
    def __init__(self, *args, **kwargs):
        CDIHandler.__init__(self, *args, **kwargs)
        ttk.Frame.__init__(self, *args, **kwargs)
        self._top_widgets = []
        if len(args) < 1:
            raise ValueError("at least one argument (parent) is required")
        self.parent = args[0]
        self.root = args[0]
        if hasattr(self.parent, 'root'):
            self.root = self.parent.root
        self._container = self  # where to put visible widgets
        self._treeview = None
        self._gui(self._container)

    def _gui(self, container):
        if self._top_widgets:
            raise RuntimeError("gui can only be called once unless reset")
        self._status_var = tk.StringVar(self)
        self._status_label = ttk.Label(container, textvariable=self._status_var)
        self.grid(sticky=tk.NSEW, row=len(self._top_widgets))
        self._top_widgets.append(self._status_label)
        self._overview = ttk.Frame(container)
        self.grid(sticky=tk.NSEW, row=len(self._top_widgets))
        self._top_widgets.append(self._overview)
        self._treeview = ttk.Treeview(container)
        self.grid(sticky=tk.NSEW, row=len(self._top_widgets))
        self.rowconfigure(len(self._top_widgets), weight=1)  # weight=1 allows expansion
        self._top_widgets.append(self._treeview)
        self._branch = ""  # top level of a Treeview is ""
        self._current_iid = 0   # id of Treeview element

    def clear(self):
        while self._top_widgets:
            widget = self._top_widgets.pop()
            widget.grid_forget()
        self._gui()
        self.set_status("Display reset.")

    def downloadCDI(self, farNodeID, callback=None):
        self.set_status("Downloading CDI...")
        super().downloadCDI(farNodeID, callback=callback)

    def set_status(self, message):
        self._status_var.set(message)

    def cdi_refresh_callback(self, event_d):
        """Handler for incoming CDI tag
        (Use this for callback in downloadCDI, which sets parser's
        _download_callback)

        Args:
            event_d (dict): Document parsing state info:
                - 'element' (SubElement): The element
                  that has been completely parsed ('</...>' reached)
                - 'error' (str): Message of failure (requires 'done' if stopped).
                - 'done' (bool): If True, downloadCDI is finished.
                  Though document itself may be incomplete if 'error' is
                  also set, stop tracking status of downloadCDI
                  regardless.
        """
        done = event_d.get('done')
        error = event_d.get('error')
        message = event_d.get('message')
        show_message = None
        if error:
            show_message = error
        elif message:
            show_message = message
        elif done:
            show_message = "Done loading CDI."
        if show_message:
            self.root.after(0, self.set_status, show_message)
        if done:
            return
        self.root.after(0, self._add_cdi_element, event_d)

    def _add_cdi_element(self, event_d):
        element = event_d.get('element')
        segment = event_d.get('segment')
        groups = event_d.get('groups')
        tag = element.tag
        if not tag:
            logger.warning("Ignored blank tag for event: {}".format(event_d))
            return
        tag = tag.lower()
        # TODO: handle start tags separately (Branches are too late tobe
        #   created here since all children are done).
        index = "end"  # "end" is at end of current branch (otherwise use int)
        if tag == "segment":
            pass
        elif tag == "group":
            pass
        elif tag == "acdi":
            # Configuration Description Information - Standard - section 5.1
            pass
        elif tag in ("int", "string", "float"):
            name = ""
            for child in element:
                if child.tag == "name":
                    name = child.text
                    break
            self._treeview.insert(self._branch, index, iid=self._current_iid,
                                  text=name)
            # values=(), image=None
            self._current_iid += 1  # TODO: associate with SubElement
            #  and/or set values keyword argument to create association(s)
        elif tag == "cdi":
            pass
        else:
            logger.warning("Ignored {}".format(tag))
