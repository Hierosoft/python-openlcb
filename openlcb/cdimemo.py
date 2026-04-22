from collections import OrderedDict
import json
import math
import xml.etree.ElementTree
# import xml.etree.ElementTree as ET

from typing import List, Optional, Union

from openlcb.cdivar import FLOAT_MAXIMUMS, NUM_TYPES, CDIVar
from openlcb.message import Message


def element_ordered(el: xml.etree.ElementTree.Element):
    od = OrderedDict()
    od['tag'] = el.tag
    od['attrib'] = el.attrib
    return od


class CDIMemo:
    """Store parsing state info as a tree (This is a tree node)

    Attributes:
        address (int, optional): Memory address of data element
            (calculated from segment ancestor and size and/or offset
            of previous elements and offset of this element).
        content (str|None): string content (collected by parser from
            between the start and end tag).
        children (List[CDIMemo]): List of children (Therefore not
            complete until onPopScope, but you can also check if .end is
            True in asynchronous scopes).
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
        self.cdivar = None  # type: CDIVar|None
        self.children = []  # type: List[CDIMemo]
        # Set by DataProcessor such as XMLDataProcessor:
        self.progress_ratio = None  # type: float|None
        self.progress_count = None  # type: int|None
        self.expected_size = None  # type: int|None

    def getTag(self):
        if self.element is None:
            return self.tag  # May have been set manually (stray end tag)
        return self.element.tag

    def getChildContentN(self, tag, className) -> Union[int, float, None]:
        for child in self.children:
            if child.tag == tag:
                if child.content is None:
                    return None
                if className == "int":
                    if not child.content.strip():
                        return None
                    return int(child.content.strip())
                elif className == "float":
                    if not child.content.strip():
                        return None
                    return float(child.content.strip())
                else:
                    raise NotImplementedError(
                        "className {} is not implemented in getChildContent"
                        .format(className))
        return None

    def getChildContent(self, tag) -> Union[str, None]:
        for child in self.children:
            if child.tag == tag:
                if child.content is None:
                    return None
                return child.content.strip()
        return None

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

    @staticmethod
    def to_dict(cm):
        d = OrderedDict()
        for k, v in cm.__dict__.items():
            # if k == 'children':
            #     continue
            if k == 'parent':
                continue
            if isinstance(v, xml.etree.ElementTree.Element):
                d[k] = element_ordered(v)
                continue
            d[k] = v
        return d

    def __str__(self):
        return json.dumps(CDIMemo.to_dict(self), default=CDIMemo.to_dict)

    def toCDIVar(self):
        """Create a CDIVar from descriptors (child elements of self).
        See LCC "Configuration Description Information" Standard.
        """
        result = CDIVar(self.tag)
        assert (self.tag is not None) and (self.tag.strip())
        result.className = self.tag.lower()
        if self.element:
            result.floatFormat = self.element.attrib.get('floatFormat')
        this_t = NUM_TYPES.get(self.tag) if self.tag else None
        if this_t is not None:
            result.min = self.getChildContentN("min", result.className)
            result.max = self.getChildContentN("max", result.className)
            result.default = self.getChildContentN("default", result.className)
        result.size = self.getSize()

        if result.className == "int":
            if result.min is None:
                result.min = 0
            elif result.min < 0:
                result.signed = True
            # if self.size is not None:
            if result.size not in [1, 2, 4, 8]:
                raise AttributeError(
                    f"expected 1,2,4,8 for int size, got {result.size}"
                    f" in children={json.dumps(self.children, sort_keys=True, indent=2,
                                      default=CDIMemo.to_dict)}")
            if result.max is None:
                if result.signed:
                    result.max = math.pow(2, result.size * 8 - 1) - 1
                else:
                    result.max = math.pow(2, result.size * 8)
        elif result.className == "float":
            result.signed = True  # float is always signed in CDI
            if result.min is None:
                result.min = 0.0
            # if self.size is not None:
            if result.size not in [2, 4, 8]:
                raise AttributeError(
                    f"expected 2,4,8 for float size, got {result.size}")
            if result.max is None:
                assert isinstance(result.size, int)
                result.max = FLOAT_MAXIMUMS[result.size * 8]
        return result

    def getSize(self):
        if self.element is None:
            return None
        size = self.element.attrib.get('size')
        if size is None:
            return None
        return int(size)
