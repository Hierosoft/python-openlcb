import xml.etree.ElementTree

from typing import Optional, Union

from openlcb.message import Message


class CDIMemo:
    """Store parsing state info as a tree (This is a tree node)

    Attributes:
        address (int, optional): Memory address of data element
            (calculated from segment ancestor and size and/or offset
            of previous elements and offset of this element).
        content (str|None): string content (collected by parser from
            between the start and end tag).
        done (bool): If True, downloadCDI is finished. Though document
            itself may be incomplete if 'error' is also set, stop
            tracking status of downloadCDI regardless.
        element (SubElement): The element that has been completely
            parsed ('</...>' reached)
        end (bool): False to start a deeper scope, or True for end tag,
            which exits current scope (last created Treeview branch in
            this case, or top if getBranch() would be None).
        error (str): Message of failure (requires 'done' if stopped).
        iid (str): Treeview branch id (no parent when top of Treeview)
        name (str): Name (determined by `name` child element content).
        stray (bool): The end tag is misplaced (doesn't match a start
            tag) due to bad xml or incorrect parsing.
    """
    def __init__(self, tag: Union[str, None] = None,
                 element: Union[xml.etree.ElementTree.Element, None] = None,
                 status: Union[str, None] = None,
                 parent: Optional['CDIMemo'] = None):
        self.tag = tag  # type: str|None
        # self.name = None  # type: str|None
        self.element = element  # type: xml.etree.ElementTree.Element|None
        self.status = status   # type: str|None
        self.error = None  # type: str|None
        self.done = False  # type: bool
        self.end = False  # type: bool
        self.parent = parent  # type: CDIMemo|None
        self.stray = False  # type: bool
        self.content = None  # type: str|None
        self.message: Union[Message, None] = None  # type: Message|None
        self.iid = None  # type: str|None
        self.address = None  # type: int|None

    def getTag(self):
        if self.element is None:
            return self.tag  # May have been set manually (stray end tag)
        return self.element.tag

    def copy(self):
        cm = CDIMemo()
        for k, v in self.__dict__.items():
            setattr(cm, k, v)
        return cm

    def getBranch(self, default=None) -> Union[str, None]:
        """Get tree branch widget iid if any."""
        if self.iid is None:
            if self.parent is None:
                return default
            return self.parent.getBranch(default=default)
        return self.iid

    def __setitem__(self, key, value):
        if self.element is None:
            raise AttributeError(
                "No element. Can't set attribute {}."
                .format(repr(key)))
        if key not in self.element.attrib:
            raise AttributeError(
                "Invalid attribute {}. Expected: {}"
                .format(repr(key), list(self.element.attrib.keys())))
        self.element.attrib[key] = value

    def __getitem__(self, key):
        if self.element is None:
            raise AttributeError("No element is set.")
        return self.element.attrib[key]

    def get(self, key):
        return self.element.attrib.get(key) if self.element else None

    def __repr__(self):
        return repr(self.__dict__)

    def __str__(self):
        return str(self.__dict__)
