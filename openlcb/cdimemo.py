from collections import OrderedDict
import copy
import json
import math
import xml.etree.ElementTree
# import xml.etree.ElementTree as ET

from typing import Dict, List, Optional, Union
from logging import getLogger

from openlcb.cdivar import CLASSNAME_TYPES, FLOAT_MAXIMUMS, NUM_TYPES, CDIVar
from openlcb.message import Message
from openlcb.dataprocessormemo import DataProcessorMemo

logger = getLogger(__name__)


def element_ordered(el: xml.etree.ElementTree.Element):
    od = OrderedDict()
    od['tag'] = el.tag
    od['attrib'] = el.attrib
    return od


class CDIMemo(DataProcessorMemo):
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
        space (int|None): The memory space address (May be one in
            MemorySpace values, or not if vendor-specific such as
            defined in CDI etc. See replicatedTree in XMLDataProcessor).
        stray (bool): The end tag is misplaced (doesn't match a start
            tag) due to bad xml or incorrect parsing.
        tail (str|None): Content following the end tag (not used in
            OpenLCB CDI/FDI standards).
    """
    def __init__(self, tag: Union[str, None] = None,
                 element: Union[xml.etree.ElementTree.Element, None] = None,
                 status: Union[str, None] = None,
                 parent: Optional['CDIMemo'] = None,
                 document: Optional['XMLDocumentProcessor'] = None):
        DataProcessorMemo.__init__(self)
        self.tag = tag  # type: str|None
        # self.name = None  # type: str|None
        self.element = element  # type: xml.etree.ElementTree.Element|None
        self.parent = parent  # type: CDIMemo|None
        self.stray = False  # type: bool
        self.content = None  # type: str|None
        self.tail = None  # type: str|None
        # TODO: Set tail (unused in OpenLCB CDI/FDI standards, but allowed in XML)
        self.iid = None  # type: str|None
        self.address = None  # type: int|None
        self.space = None  # type: int|None
        self.cdivar = None  # type: CDIVar|None
        self.children = []  # type: List[CDIMemo]
        self.document: Union[Optional['XMLDocumentProcessor'], None] = document

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
        return self.__copy__()

    def __copy__(self):
        cm = CDIMemo()
        for k, v in self.__dict__.items():
            setattr(cm, k, v)
        return cm

    def __deepcopy__(self, memo: dict):
        """Allow deepcopy on this class.
        Place id of new object in memo dict
        (prevents infinite recursion).
        See <https://stackoverflow.com/a/15774013/4541104>.
        """
        cm = type(self)()
        memo[id(self)] = cm
        for k, v in self.__dict__.items():
            if k == 'parent':
                # prevent invalid container
                continue
            if k == "document":
                # prevent un-pickle-able object (& invalid container)
                continue
            setattr(cm, k, copy.deepcopy(v, memo))
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
            if k == 'document':
                continue
            if isinstance(v, xml.etree.ElementTree.Element):
                d[k] = element_ordered(v)
                continue
            d[k] = v
        return d

    def __str__(self):
        return json.dumps(CDIMemo.to_dict(self), default=CDIMemo.to_dict)

    def toCDIVar(self):
        # type: () -> CDIVar
        """Create a CDIVar from descriptors (child elements of self).
        See LCC "Configuration Description Information" Standard.

        NOTE: The `address` is only correct if this CDIMemo has been
        replicated (such as in replicatedTree or self.replicated_root).
        """
        # result = CDIVar(self.tag)
        assert (self.tag is not None) and (self.tag.strip())
        className = self.tag.lower()
        result_floatFormat = None
        if self.element:
            result_floatFormat = self.element.attrib.get('floatFormat')
        this_t = NUM_TYPES.get(self.tag) if self.tag else None
        result_min = None
        result_max = None
        result_default = None
        result_size = self.getSize()
        if this_t is not None:
            assert result_size is not None, \
                f"size is required for {this_t.__name__}"
            result_min = self.getChildContentN("min", className)
            result_max = self.getChildContentN("max", className)
            default_n = self.getChildContentN("default", className)
            if default_n is not None:
                result_default = CDIVar.fromNumber(default_n, className,
                                                   result_size)
                # default_var = CDIVar(className, _size=result_size)
                # if isinstance(default_n, int):
                #     assert self.tag == "int"
                #     default_var.setInt(default_n)
                # else:
                #     assert self.tag == "float"
                #     default_var.setFloat(default_n)
                # assert default_var.data is not None
                # result_default = bytearray(default_var.data)
        # Size must be gotten ahead of time since CDIVar constructor
        #   enforces size:
        if result_min is not None:
            assert result_size is not None, \
                f"size is required with min (className={className})"
            result_min = CDIVar.fromNumber(result_min, className,
                                           _size=result_size)
        if result_max is not None:
            assert result_size is not None, \
                f"size is required with min (className={className})"
            result_max = CDIVar.fromNumber(result_max, className,
                                           _size=result_size)
        result = CDIVar(self.tag, _min=result_min, _max=result_max,
                        _size=result_size, _default=result_default)
        result.address = self.address  # only set in replicatedTree()
        result.space = self.space
        result.floatFormat = result_floatFormat
        result.name = self.getChildContent("name")
        if not result.name and (self.tag in CLASSNAME_TYPES):
            raise NotImplementedError(f"Can't get name for {self}")

        if result.className == "int":
            if result.min is None:
                result.min = 0
            elif result.min < 0:
                result.signed = True
            # if self.size is not None:
            if result.size not in [1, 2, 4, 8]:
                children_msg = json.dumps(self.children, sort_keys=True,
                                          indent=2,
                                          default=CDIMemo.to_dict)
                raise AttributeError(
                    f"expected 1,2,4,8 for int size, got {result.size}"
                    f" in children={children_msg}")
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
        if self.tag == "eventid":
            return 8
        if self.element is None:
            return None
        size = self.element.attrib.get('size')
        if size is None:
            return None
        return int(size)

    def addChildren(self) -> None:
        """Recursively build the full CDIMemo tree from self.element.

        Populates ``self.children`` with proper CDIMemo instances
        (one per direct child element). Each child memo also gets
        its own children built recursively.

        Preserves original ``.content`` from the parsed tree.
        """
        if self.element is None:
            self.children = []
            return

        self.children = []
        if self.element.text:
            self.content = self.element.text
        elif self.element.tag.lower() in ("name", "description"):
            logger.warning(
                f"{self.element.tag} has no content.")

        if self.element.tail:
            self.tail = self.element.tail

        for child_elem in list(self.element):  # list() fixes concurrency issue
            child_memo = CDIMemo(
                tag=child_elem.tag,
                element=child_elem,
                parent=self,
                document=self.document
            )
            child_memo.addChildren()  # recursive
            self.children.append(child_memo)
