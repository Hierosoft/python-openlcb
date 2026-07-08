"""
Examples GUI

This file is part of the python-openlcb project
(<https://github.com/bobjacobsen/python-openlcb>).

Contributors: Poikilos

Purpose: Provide an easy way to enter settings for examples and run them.
- tkinter is used since it is included in Python (except in Debian-based
  distros, which require the python3-tk package due to Debian requirements
  for GUI components to be packaged separately).
"""
import json
import os
import platform
import subprocess
import sys
import threading

from logging import getLogger

from openlcb.memoryspace import MemorySpace

try:
    import tkinter as tk
except ImportError:
    print("\nYou must first install python3-tk if using apt or other system"
          " that requires tkinter to be in a separate package from Python.",
          file=sys.stderr)
    raise
from tkinter import ttk
from collections import OrderedDict, deque


from examples_settings import Settings  # do 1st to fix path if no pip install


from openlcb.cdimemo import CDIMemo
from openlcb.message import Message
from openlcb.xmldataprocessor import XMLDataProcessor
from openlcb.mti import MTI
from openlcb.nodeid import NodeID
from openlcb.openlcbnetwork import OpenLCBNetwork

from openlcb.tcplink.tcpsocket import TcpSocket
from examples.tkexamples.cdiform import CDIForm

from openlcb import emit_cast, formatted_ex
from openlcb.tcplink.mdnsconventions import id_from_tcp_service_name

from typing import Callable, OrderedDict as TypingOrderedDict, Union

zeroconf_enabled = False
try:
    from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
    zeroconf_enabled = True
except ImportError:
    class Zeroconf:
        """Placeholder for when zeroconf is *not* present"""
        pass

    class ServiceListener:
        """Placeholder for when zeroconf is *not* present"""
        pass

    class ServiceBrowser:
        """Placeholder for when zeroconf is *not* present"""
        pass

if __name__ == "__main__":
    logger = getLogger(__file__)
else:
    logger = getLogger(__name__)


class MyListener(ServiceListener):
    pass


class DataField():
    """Store various widgets and data associated with a single data field.
    Attributes:
        label (Label): A label associated with (usually left of) the field.
        var (Union[StringVar,IntVar]): Makes value accessible in a uniform way
            (self.var.get()) regardless of widget class.
        widget (Misc): The widget used to enter data (value is stored in var).
        button (Button): optional command button.
        tooltip (Label): An extra label associated with (usually below) the
            field.
    """
    def __init__(self):
        self.label = None
        self.var = None
        self.widget = None
        self.button = None
        self.tooltip = None
        self.groups = None
        self.segment = None

    def get(self):
        return self.var.get()

    def set(self, value):
        self.var.set(value)


class MainForm(ttk.Frame):
    """The interface to choose device(s) for examples.

    The program is organized into fields. Each field contains a label, entry
    widget, and potentially a tooltip Label and command button.

    - The entry widget for each field may be a ttk.Entry, ttk.Combobox, or
      potentially another ttk widget subclass.

    - Each field has a key. Only keys in self.settings are directly used
      as settings.

    Attributes:
        w1 (Union[Tk,Frame]): The Tk (first and only Window typically). It is
            set automatically to self.winfo_toplevel() by gui method.
        parent (Union[Tk,Frame]): Tk (same as self.w1 in that case) or tk.Frame
            instance, whichever contains self.
        fields (list[DataField]): A list of settings.
        example_buttons (OrderedDict[Button]): The example module name is the
            key and the Button instance is the value.
        example_modules (OrderedDict[str]): The example
            module name is the key, and the full path is the value. If
            examples are made modular, the value will not be necessary, but
            for now just run the file in another Python instance (See
            run_example method).

    Args:
        parent (Union[Tk,Frame,0]): The Tk (first and only Window typically) or
            tk.Frame, either way containing self. 0 to make a new Tk. The
            tk instance is always stored in self.w1 regardless of parent.
    """

    def __init__(self, parent):
        self.run_button = None
        self.examples_label = None
        self.zeroconf = None
        self.listener = None
        self.browser = None
        self.errors = deque()
        self.root = parent
        self._connect_thread = None
        try:
            self.settings = Settings()
        except json.decoder.JSONDecodeError as ex:
            self.errors.append(
                "Error: {} not loaded! {}".format(Settings.SETTINGS_NAME, ex)
            )
            # Try again (load defaults), since Settings is expected to
            #   have backed up & moved the bad JSON file:
            self.settings = Settings()
        self.detected_services = OrderedDict()
        self.fields: TypingOrderedDict[str, tk.Entry] = OrderedDict()
        self.proc = None
        self._gui(parent)
        self.w1.after(1, self.onFormLoaded)  # must go after gui
        self.example_modules = OrderedDict()
        self.example_buttons = OrderedDict()
        if zeroconf_enabled:
            self.zeroconf = Zeroconf()
            self.listener = MyListener()
            self.listener.update_service = self.updateService
            self.listener.remove_service = self.removeService
            self.listener.add_service = self.addService

    def onFormLoaded(self):
        self.loadSettings()
        self.loadExamples()
        count = self.showNextError()
        if not count:
            self.setStatus(
                "Welcome!"
            )
        # else show_next_error should have already set status label text.

    def showNextError(self):
        if not self.errors:
            return 0
        error = self.errors.popleft()
        if not error:
            return 0
        self.setStatus(error)
        return 1

    def removeExamples(self):
        for module_name, button in self.example_buttons.items():
            button.grid_forget()
            self.row -= 1
        if self.examples_label:
            self.examples_label.grid_forget()
            self.examples_label = None
        if self.run_button:
            self.run_button.grid_forget()
            self.run_button = None
        self.example_buttons.clear()
        self.example_modules.clear()

    def loadExamples(self):
        self.removeExamples()
        self.example_row = 0
        self.examples_label = ttk.Label(
            self.example_tab,
            text=("These examples run in the background without a GUI."
                  "\nHowever, the interface above can setup settings.json"
                  "\n (usable by any of them, saved when run is clicked)."),
        )
        self.examples_label.grid(row=0, column=1)

        self.run_button = ttk.Button(
            self.example_tab,
            text="Run",
            command=self.runExample,
            # command=lambda x=name: self.run_example(module_name=x),
            # x=name is necessary for early binding, otherwise all
            # lambdas will have the *last* value in the loop.
        )
        self.run_button.grid(row=0, column=0, sticky=tk.W)
        self.example_row += 1

        repo_dir = os.path.dirname(os.path.realpath(__file__))
        self.example_var = tk.IntVar()  # Shared by *all* in radio group.
        # ^ The value refers to an entry in examples:
        self.examples = []
        for sub in sorted(os.listdir(repo_dir)):
            if not sub.startswith("example_"):
                continue
            if not sub.endswith(".py"):
                continue
            sub_path = os.path.join(repo_dir, sub)
            name, _ = os.path.splitext(sub)  # name, dot+extension
            self.example_modules[name] = sub_path
            button = ttk.Radiobutton(
                self.example_group_box,
                text=name,
                variable=self.example_var,
                value=len(self.examples),
                # command=lambda x=name: self.run_example(module_name=x),
                # x=name is necessary for early binding, otherwise all
                # lambdas will have the *last* value in the loop.
            )
            self.examples.append(name)
            button.grid(row=self.example_row, column=0, sticky=tk.W)
            self.example_buttons[name] = button
            self.example_row += 1

    def runExample(self, module_name=None):
        """Run the selected example.

        Args:
            module_name (str, optional): The module name (file without
                extension) of the example. Defaults to selected
                Radiobutton.
        """
        if not module_name:
            # for name, radiobutton in self.example_buttons.items():
            index = self.example_var.get()
            if index is None:
                self.setStatus("Select an example first.")
                return
            module_name = self.examples[index]

        self.setStatus("")
        node_ids = (
            self.fields['localNodeID'].get(),
            self.fields['farNodeID'].get(),
        )
        for node_id in node_ids:
            if (":" in node_id) or ("." not in node_id):
                self.setStatus("Error: expected dot-separated ID")
                return
        self.saveSettings()
        module_path = self.example_modules[module_name]
        args = (sys.executable, module_path)
        self.setStatus("Running {} (see console for results)..."
                       .format(module_name))

        self.enableButtons(False)
        try:
            self.proc = subprocess.Popen(
                args,
                shell=True,
                # close_fds=True, close file descriptors >= 3 before running
                # stdin=None, stdout=None, stderr=None,
            )
        finally:
            self.enableButtons(True)

    def enableButtons(self, enable):
        state = tk.NORMAL if enable else tk.DISABLED
        if self.run_button:
            self.run_button.configure(state=state)
        for field in self.fields.values():
            if not hasattr(field, 'button') or not field.button:
                continue
            field.button.configure(state=state)

    def loadSettings(self):
        # import json
        # print(json.dumps(self.settings._meta, indent=1, sort_keys=True))

        # print("[gui] self.settings['localNodeID']={}"
        #       .format(self.settings['localNodeID']))
        for key in self.fields.keys():
            if key not in self.settings:
                # The field must not be a setting. Don't try to load
                #   (Avoid KeyError).
                continue
            self.fields[key].set(self.settings[key])
        # print("[gui] self.fields['localNodeID']={}"
        #       .format(self.fields['localNodeID'].get()))

    def saveSettings(self):
        for key, field in self.fields.items():
            if key not in self.settings:
                # Skip runtime GUI data fields such as
                #   self.fields['service_name'] that aren't directly used as
                #   settings.
                print("{} is not in settings.".format(key))
                continue
            print("{} is in settings.".format(key))
            value = field.get()
            _types = self.settings.get_types(key)
            if _types:
                if not isinstance(value, _types):
                    _type = self.settings.get_preferred_type(key)
                    # ^ Get the preferred type in case multiple are allowed
                    #   (usually float or int in that case)
                    value = _type(value)
            self.settings[key] = value
        self.settings.save()

    def _gui(self, parent):
        print("Using {}".format(self.settings.settings_path))
        # import json
        # print(json.dumps(self.settings._meta, indent=1, sort_keys=True))
        self.parent = parent
        ttk.Frame.__init__(self, self.parent)
        self.row_count = 0
        self.column_count = 0
        self.tooltip_column = 0
        self.tooltip_columnspan = 3
        self.grid_args = {
            'sticky': tk.NSEW,  # N is top ("north"), W is left, etc.
            # 'padx': 8,
            # 'pady': 8,
        }
        # self.w1.place(x=0, y=0, width=500, height=450)
        self.w1 = self.winfo_toplevel()  # a.k.a. root
        # self.parent.pack(fill=tk.BOTH)

        self.grid(sticky=tk.NSEW, row=0, column=0)  # place *self*
        # ^ Only one other widget is in the parent: statusLabel
        # self.statusSV = tk.StringVar(master=self.w1)

        self.parent.rowconfigure(0, weight=1)
        self.parent.columnconfigure(0, weight=1)
        self.row = 0
        self.addField("service_name",
                      "TCP Service name (optional, sets host&port)",
                      gui_class=ttk.Combobox, tooltip="",
                      command=self.setIdFromName,
                      command_text="Copy digits to Far Node ID")
        self.fields["service_name"].button.configure(state=tk.DISABLED)
        self.fields["service_name"].var.trace('w', self.onServiceNameChange)
        self.addField("host", "IP address/hostname",
                      command=self.detectHosts,
                      command_text="Detect")
        self.addField(
            "port",
            "Port",
            command=self.fillDefaultPort,
            command_text="Default",
        )
        self.addField(
            "localNodeID",
            "Local Node ID",
            command=self.fillDefaultLocalNodeId,
            command_text="Default",
            tooltip=('"05.*.*.*.*.*" Node IDs are for OpenLCB only:'),
        )

        self.unique_ranges_url = "https://registry.openlcb.org/uniqueidranges"
        underlined_url = \
            ''.join([letter+'\u0332' for letter in self.unique_ranges_url])
        # ^ '\u0332' is unicode for "underline previous character"
        #   and is a way of underlining without creating potential
        #   cross-platform issues when choosing a font name when creating
        #   a tk.Font instance.
        self.local_node_url_label = ttk.Label(
            self,
            text='See {}.'.format(underlined_url),
        )
        # A label is not a button, so must bind to mouse button event manually:
        self.local_node_url_label.bind(
            "<Button-1>",  # Mouse button 1 (left click)
            lambda e: self.openUrl(self.unique_ranges_url)
        )
        self.local_node_url_label.grid(row=self.row,
                                       column=self.tooltip_column,
                                       columnspan=self.tooltip_columnspan,
                                       sticky=tk.N)
        self.row += 1

        self.addField(
            "farNodeID", "Far Node ID",
            gui_class=ttk.Combobox,
            command=self.detectNodes,  # TODO: finish detect_nodes & use
            command_text="Detect",  # TODO: finish detect_nodes & use
        )

        self.addField(
            "device", "Serial Device (or COM port)",
            gui_class=ttk.Combobox,
            command=lambda: self.fillDefault("device"),
            command_text="Default",
        )

        self.addField(
            "timeout", "Remote nodes timeout (seconds)",
            gui_class=ttk.Entry,
        )

        self.addField(
            "trace", "Remote nodes logging",
            gui_class=ttk.Checkbutton,
            text="Trace",
        )

        # NOTE: load_examples (See onFormLoaded) fills Examples tab.
        self.notebook = ttk.Notebook(self)
        self.notebook.grid(sticky=tk.NSEW, row=self.row, column=0,
                           columnspan=self.column_count)
        self.row += 1
        self.cdi_row = 0
        # region based on ttk Forest Theme
        self.cdi_tab = ttk.Frame(self.notebook)
        self.cdi_tab.columnconfigure(index=0, weight=1)
        self.cdi_tab.columnconfigure(index=1, weight=1)
        self.cdi_tab.rowconfigure(index=0, weight=1)
        self.cdi_tab.rowconfigure(index=1, weight=1)
        self.notebook.add(self.cdi_tab, text="Node Configuration (CDI)")
        # endregion based on ttk Forest Theme

        self.cdi_connect_button = ttk.Button(
            self.cdi_tab,
            text="Connect",
            command=self.cdiConnectClicked,
        )
        self.cdi_connect_button.grid(row=self.cdi_row, column=0)

        self.cdi_refresh_button = ttk.Button(
            self.cdi_tab,
            text="Refresh",
            command=self.cdiRefreshClicked,
            state=tk.DISABLED,  # enabled on connect success callback
        )
        self.cdi_refresh_button.grid(row=self.cdi_row, column=1)
        self.cdi_row += 1

        self.cdiSettingFrame = ttk.Frame(self.cdi_tab)
        self.cdiSettingFrame.grid(row=self.cdi_row+1, column=1)
        # NOTE: ^ See self.cdi_form.setSettingsContainer in setupNetwork
        # ^ +1 to row so it is across from _treeview
        #   below invisible status label in second row on left
        self.cdi_row += 1

        self.network = None
        self.cdi_form = None  # type: CDIForm|None
        # ^ CDIForm or other XMLDataProcessor subclass

        self.example_tab = ttk.Frame(self.notebook)
        self.example_tab.columnconfigure(index=0, weight=1)
        self.example_tab.columnconfigure(index=1, weight=1)
        self.example_tab.rowconfigure(index=0, weight=1)
        self.example_tab.rowconfigure(index=1, weight=1)
        self.notebook.add(self.example_tab, text="Other Examples")

        self.example_group_box = self.example_tab

        # The status widget is the only widget other than self which
        #   is directly inside the parent widget (forces it to bottom):
        self.statusLabel = ttk.Label(self.parent)
        self.statusLabel.grid(sticky=tk.S, row=1, column=0,
                              columnspan=self.column_count)
        # Use the counts determined so far to weight column width equally (use
        #   same weight):
        if self.row > self.row_count:
            self.row_count = self.row
        if self.column > self.column_count:
            self.column_count = self.column
        for column in range(self.column_count):
            self.columnconfigure(column, weight=1)
        # for row in range(self.row_count):
        #     self.rowconfigure(row, weight=1)
        # self.rowconfigure(self.row_count-1, weight=1)  # make last row expand

    def setupNetwork(self):
        self.network = OpenLCBNetwork(self.getValue('localNodeID'))
        self.cdi_form = CDIForm(self.network.canLink, self.cdi_tab)
        self.cdi_form.setSettingsContainer(self.cdiSettingFrame)
        self.cdi_form.setStatusCallback(self.setStatus)
        # ^ formerly OpenLCBNetwork() subclass
        # ^ CDIForm has ttk.Treeview etc.
        self.cdi_form.canLink.registerMessageReceivedListener(
            self.handleMessage)
        self.cdi_form.grid(row=self.cdi_row)

    def handleMessage(self, message: Message):
        """Off-thread message handler.
        This is called by the OpenLCB network stack which is controlled
        by the socket loop thread, so we must use self.root.after to
        trigger methods which affect the GUI (such as _handleMessage).
        """
        self.root.after_idle(self._handleMessage, message)

    def _handleMessage(self, message: Message):
        """Main thread Message handler.
        Use self.root.after to trigger this, since code here affects the
        GUI (Only main thread can access the GUI)!
        """
        if message.mti == MTI.Link_Layer_Up:
            self._handleConnect()
        elif message.mti == MTI.Link_Layer_Down:
            self._handleDisconnect()

    def _handleDisconnect(self):
        """Handle Link_Layer_Up Message.
        Affects GUI, so run from main thread or via self.root.after.
        """
        # formerly part of _connectStateChanged
        # formerly called from connectStateChanged such as on connect or
        # _listen thread

        # Can't communicate with LCC network, so disable related widget(s):
        self.cdi_refresh_button.configure(state=tk.DISABLED)
        self.cdi_connect_button.configure(state=tk.NORMAL)
        self.setStatus("LCC network disconnected.")

    def _handleConnect(self):
        """Handle Link_Layer_Down Message
        Affects GUI, so run from main thread or via self.root.after.
        """
        ready_message = 'Ready to load CDI (click "Refresh").'
        # if event_d.get('command') == "connect":
        self.cdi_refresh_button.configure(state=tk.NORMAL)
        self.setStatus(ready_message)
        if self.cdi_form is not None:
            self.cdi_form.setStatus("")  # Set caption above CDI tree
            #  (Not populated yet during _handleConnect).
        print(ready_message)

    def _connect(self):
        userNodeID = NodeID(self.getValue('localNodeID'))  # assert good NodeID
        if self.network is None:
            self.setupNetwork()
        elif self.network.canLink.localNodeID != userNodeID:
            self.network.physicalLayer.physicalLayerDown()
            self.setupNetwork()
        host_var = self.fields.get('host')
        host = host_var.get()
        port_var = self.fields.get('port')
        port = port_var.get()
        if port:
            port = int(port)
        else:
            raise TypeError("Expected int, got {}".format(emit_cast(port)))
        # self.cdi_form.connect(host, port, localNodeID)
        self.saveSettings()
        self.cdi_connect_button.configure(state=tk.DISABLED)
        self.cdi_refresh_button.configure(state=tk.DISABLED)
        msg = "connecting to {}...".format(host)
        self.cdi_form.setStatus(msg)
        detectButton = self.fields['farNodeID'].button
        detectButton.configure(state=tk.NORMAL)

        result = None
        try:
            self._tcp_socket = TcpSocket()
            # self._sock.settimeout(30)
            self._tcp_socket.connect(host, port)
            # self.cdi_form.setConnectHandler(self.connectStateChanged)
            # ^ See message.mti == MTI Link_Layer_Down instead.
            result = self.network.startListening(
                self._tcp_socket,
            )
            self._connect_thread = None
            # self.cdi_connect_button.configure(state=tk.NORMAL)
        except Exception as ex:
            if self.cdi_form.getStatus() == msg:
                # If error wasn't shown, clear startup message.
                self.cdi_form.setStatus("")
            self.setStatus("Connect failed. {}".format(formatted_ex(ex)))
            self.cdi_connect_button.configure(state=tk.NORMAL)
            raise  # show traceback still, in case in an IDE or Terminal.
        return result

    def cdiConnectClicked(self):
        self._connect_thread = threading.Thread(
            target=self._connect,
            daemon=True,  # True prevents continuing when trying to exit
        )
        self._connect_thread.start()
        # This thread may end quickly after connection since
        #   start_receiving starts a thread.
        self.cdi_connect_button.configure(state=tk.DISABLED)
        self.cdi_connect_button.configure(state=tk.DISABLED)

    def cdiRefreshClicked(self):
        self.cdi_connect_button.configure(state=tk.DISABLED)
        self.cdi_refresh_button.configure(state=tk.DISABLED)
        farNodeID = self.getValue('farNodeID')
        if not farNodeID:
            self.setStatus('Set "Far node ID" first.')
            return
        print("Querying farNodeID={}".format(repr(farNodeID)))
        self.setStatus("Downloading CDI...")
        assert self.cdi_form is not None
        threading.Thread(
            target=self.downloadCDI,
            args=(farNodeID,),
            # kwargs={},
            daemon=True,
        ).start()

    def downloadCDI(self, farNodeID: str):
        """Download Configuration Description Information XML from the node.

        Args:
            farNodeID (str): Any valid node ID.
        """
        self.setStatus("Downloading CDI...")
        assert self.cdi_form is not None
        assert self.network is not None
        try:
            self.network.download(farNodeID, MemorySpace.CDI,
                                  self.cdi_form)
        except KeyError as ex:
            self.setStatus("The address was not correct: {}"
                           .format(formatted_ex(ex)))
            raise

    def getValue(self, key):
        field = self.fields.get(key)
        if not field:
            raise KeyError("Invalid form field {}".format(repr(key)))
        return field.get()

    def setIdFromName(self):
        id = self.getIdFromName(update_button=True)
        if not id:
            self.setStatus(
                "The service name {} does not contain an LCC ID"
                " (Does not follow hardware convention).")
            return
        self.fields['farNodeID'].var.set(id)
        self.setStatus(
            "Far Node ID has been set to {} portion of service name."
            .format(repr(id)))
        self.cdi_connect_button.configure(state=tk.NORMAL)

    def getIdFromName(self, update_button=False):
        lcc_id = id_from_tcp_service_name(
            self.fields['service_name'].var.get())
        if update_button:
            if not lcc_id:
                self.fields["service_name"].button.configure(state=tk.DISABLED)
            else:
                self.fields["service_name"].button.configure(state=tk.NORMAL)
        return lcc_id

    def onServiceNameChange(self, index, value, op):
        key = self.fields['service_name'].get()
        _ = self.getIdFromName(update_button=True)
        info = self.detected_services.get(key)
        if not info:
            # The user may be typing, so don't spam screen with messages,
            #   just ignore incomplete entries.
            return
        # We got info, so use the info to set *other* fields:
        self.fields['host'].set(info['server'].rstrip("."))
        # ^ Remove trailing "." to prevent getaddrinfo failed.
        self.fields['port'].set(info['port'])
        self.setStatus("Hostname & Port have been set ({server}:{port})"
                       .format(**info))

    def addField(self, key, caption, gui_class=ttk.Entry, command=None,
                 command_text=None, tooltip=None, text=None):
        """Generate a uniform data field that may or may not affect a setting.

        The row(s) for the data field will start at self.row, and self.row will
        be incremented for (each) row added by this function.

        Args:
            caption (str): Text for the label.
            key (str): Key to store the widget.
            gui_class (Misc): The ttk widget class or function to use to create
                the data entry widget (field.widget).
            command (function, optional): Command for button. Defaults to None.
            command_text (str, optional): Text for button. Defaults to None.
            tooltip (str, optional): Add a tooltip tk.Label as field.tooltip
                with this text. Added even if "". Defaults to None (not added
                in that case).
            text (str, optional): Text on the input widget itself (only
                applies to gui_class Checkbutton).
        """
        # self.row should already be set to an empty row.
        self.column = 0  # Return to beginning of row

        if command:
            if not command_text:
                raise ValueError("command_caption is required for command.")
        if command_text:
            if not command:
                raise ValueError("command is required for command_caption.")

        field = DataField()
        field.label = ttk.Label(self, text=caption)
        field.label.grid(row=self.row, column=self.column, **self.grid_args)
        self.host_column = self.column
        self.column += 1
        self.fields[key] = field
        if gui_class in (ttk.Checkbutton, ttk.Checkbutton):
            field.var = tk.BooleanVar(self.w1)
            # field.var.set(True)
            field.widget = gui_class(
                self,
                # onvalue=True,
                # offvalue=False,
                variable=field.var,
                text=text,
            )
        else:
            field.var = tk.StringVar(self.w1)
            field.widget = gui_class(
                self,
                textvariable=field.var,
            )
        field.widget.grid(row=self.row, column=self.column, **self.grid_args)
        self.column += 1

        if command:
            field.button = ttk.Button(self, text=command_text,
                                      command=command)
            field.button.grid(row=self.row, column=self.column,
                              **self.grid_args)
        self.column += 1  # go to next column even if button wasn't added,
        #   to keep columns uniform in case another column is added.

        self.row += 1

        # return field
        if tooltip is not None:
            # Even if "", still add it (used to provide feedback at runtime)
            field.tooltip = ttk.Label(self, text=tooltip)
            field.tooltip.grid(row=self.row, column=self.tooltip_column,
                               columnspan=self.tooltip_columnspan, sticky=tk.N)
            # ^ tk.N ("north') is top. Stick to top since the tip describes the
            #   field.widget above it.
            # ^ **self.gridargs is not necessary here (sticky is always tk.N).
            self.row += 1
            if self.tooltip_column >= self.column:
                self.column = self.tooltip_column + 1

        if self.column > self.column_count:
            self.column_count = self.column

    def openUrl(self, url):
        import webbrowser
        webbrowser.open_new_tab(url)

    def fillDefaultLocalNodeId(self):
        self.fillDefault('localNodeID')

    def fillDefaultPort(self):
        self.fillDefault('port')

    def fillDefault(self, key):
        self.fields[key].set(self.settings.getDefault(key))

    def getStatus(self):
        # See also CDIForm
        return self.statusLabel.get()

    def setStatus(self, msg):
        # See also CDIForm
        self.statusLabel.configure(text=msg)

    def setTooltip(self, key, msg):
        self.fields[key].tooltip.configure(text=msg)

    def showServices(self):
        self.fields['service_name'].widget['values'] = \
            list(self.detected_services.keys())

    def updateService(self, zc: Zeroconf, type_: str, name: str) -> None:
        if name in self.detected_services:
            self.detected_services[name]['type'] = type_
            print(f"Service {name} updated")
        else:
            self.detected_services[name] = {'type': type_}
            print(f"Warning: {name} was not present yet during update.")
        self.showServices()

    def removeService(self, zc: Zeroconf, type_: str, name: str) -> None:
        if name in self.detected_services:
            del self.detected_services[name]
            self.setStatus(f"{name} disconnected from the Wi-Fi/LAN")
            print(f"Service {name} removed")
        else:
            print(f"Warning: {name} was already removed.")
        self.showServices()

    def addService(self, zc: Zeroconf, type_: str, name: str) -> None:
        """
        This must use name as key, since multiple services can be advertised by
        one server!
        """
        info = zc.get_service_info(type_, name)
        if name not in self.detected_services:
            self.detected_services[name] = {}
            self.detected_services[name]['type'] = info.type
            # By now we only have ones where type==servicetype
            #   (See detect_hosts) unless servicetype is set to None.
            self.detected_services[name]['server'] = info.server  # hostname
            self.detected_services[name]['port'] = info.port
            self.detected_services[name]['properties'] = info.properties
            # ^ properties is a dict potentially containing various info
            #   (no properties are known to be useful in this case)
            self.detected_services[name]['addresses'] = info.addresses
            # ^ addresses is a list of bytes objects
            # other info attributes: priority, weight, added, interface_index
            self.setTooltip(
                'service_name',
                f"Found {name} on Wi-Fi/LAN. Select an option above."
            )
            print(f"Service {name} added, service info: {info}")
        else:
            print(f"Warning: {name} was already added.")
        self.showServices()

    def detectHosts(self, servicetype="_openlcb-can._tcp.local."):
        if not zeroconf_enabled:
            self.setStatus("The Python zeroconf package is not installed.")
            return
        if not self.zeroconf:
            self.setStatus("Zeroconf was not initialized.")
            return
        if not self.listener:
            self.setStatus("Listener was not initialized.")
            return
        if self.browser:
            self.setStatus("Already listening for {} devices."
                           .format(self.servicetype))
            return
        self.servicetype = servicetype
        self.browser = ServiceBrowser(self.zeroconf, self.servicetype,
                                      self.listener)
        self.setStatus("Detecting hosts...")

    def detectNodes(self):
        self.setStatus("Detecting nodes...")
        self.setStatus("Detecting nodes...not implemented here."
                       " See example_node_implementation.")

    def exitClicked(self):
        self.top = self.winfo_toplevel()
        self.top.quit()


def main():
    root = tk.Tk()
    root.style = ttk.Style()
    if platform.system() == "Windows":
        if 'winnative' in root.style.theme_names():
            root.style.theme_use('winnative')
    elif platform.system() == "Darwin":
        if 'aqua' in root.style.theme_names():
            root.style.theme_use('aqua')
    else:
        # Linux (such as Linux Mint 22.1) usually has
        # 'clam', 'alt', 'default', 'classic'
        if 'alt' in root.style.theme_names():
            # Use 'alt' since:
            # - 'default' and 'classic' (like 'default' but fatter
            #   shading lines) may be motif-like :( (diamond-shaped
            #   radio buttons etc)
            # - 'clam' is "3D" (Windows 95-like, warm gray)
            # - 'alt' is "3D" (Windows 2000-like, cool gray)
            root.style.theme_use('alt')
        else:
            print("No theme selected. Themes: {}"
                  .format(root.style.theme_names()))

    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    window_w = round(screen_w / 2)
    window_h = round(screen_h * .8)
    x = (screen_w - window_w) // 2
    y = (screen_h - window_h) // 12
    root.geometry("{}x{}+{}+{}".format(
        window_w,
        window_h,
        x,
        y,
    ))  # WxH+X+Y format
    root.minsize = (window_w, window_h)
    main_form = MainForm(root)
    main_form.master.title(
        "Python OpenLCB Examples (Python {}.{}.{})"
        .format(sys.version_info.major, sys.version_info.minor,
                sys.version_info.micro))
    try:
        main_form.mainloop()
    finally:
        if main_form.zeroconf:
            main_form.zeroconf.close()
            main_form.zeroconf = None
    return 0


if __name__ == "__main__":
    sys.exit(main())
