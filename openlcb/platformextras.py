"""
Platform-specific information and processing that is not in Python's
builtin modules.
"""
import os
import platform

from openlcb import emit_cast

if platform.system() == "Windows":
    _cache_dir = os.path.join(os.environ['LOCALAPPDATA'], "cache")
elif platform.system() == "Darwin":
    _cache_dir = os.path.expanduser("~/Library/Caches")
else:
    _cache_dir = os.path.expanduser("~/.cache")


class ConstantClassMeta(type):
    def __setattr__(cls, name, value):
        if name in cls.__dict__:
            raise AttributeError(
                "Cannot modify constant attribute '{}'".format(name))
        super().__setattr__(name, value)


class SysDirs(metaclass=ConstantClassMeta):
    Cache = _cache_dir


file_name_extra_symbols = "-_=+.,() ~"
# ^ isalnum plus this is allowed
#   (lowest common denominator for now)


def is_file_name_char(c: str) -> bool:
    if (not isinstance(c, str)) or (len(c) != 1):
        raise TypeError("Expected 1-length str, got {}"
                        .format(emit_cast(c)))
    return c.isalnum() or (c in file_name_extra_symbols)


def clean_file_name_char(c: str, placeholder: str = None) -> str:
    if placeholder is None:
        placeholder = "_"
    else:
        assert isinstance(placeholder, str)
        assert len(placeholder) == 1
    if is_file_name_char(c):
        return c
    return placeholder


def clean_file_name(name: str, placeholder: str = None) -> str:
    assert isinstance(name, str)
    if (os.path.sep in name) or ("/" in name):
        # or "/" since Python uses that even on Windows
        #   in some module(s) such as tkinter
        raise ValueError(
            "Must only specify name not path ({} contained {})"
            .format(repr(name), repr(os.path.sep)))
    result = ""
    for c in name:
        result += clean_file_name_char(c, placeholder=placeholder)
    return result
