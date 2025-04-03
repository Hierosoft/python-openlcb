import os
import sys
import time
import unittest

from logging import getLogger
logger = getLogger(__name__)

if __name__ == "__main__":
    TESTS_DIR = os.path.dirname(os.path.realpath(__file__))
    REPO_DIR = os.path.dirname(TESTS_DIR)
    if os.path.isfile(os.path.join(REPO_DIR, "openlcb", "__init__.py")):
        sys.path.insert(0, REPO_DIR)
    else:
        logger.warning(
            "Reverting to installed copy if present (or imports will fail),"
            " since test running from repo but could not find openlcb in {}."
            .format(repr(REPO_DIR)))

import openlcb  # noqa: E402

# for brevity:
from openlcb import (  # noqa: E402
    emit_cast,
    formatted_ex,
    list_type_names,
    only_hex_pairs,
)


class TestConventions(unittest.TestCase):
    def test_only_hex_pairs(self):
        self.assertTrue(only_hex_pairs("02015700049C"))
        self.assertTrue(only_hex_pairs("02015700049c"))
        self.assertTrue(only_hex_pairs("02"))

        self.assertFalse(only_hex_pairs("02.01.57.00.04.9C"))  # contains separator  # noqa:E501
        # ^ For the positive test (& allowing elements not zero-padded) see test_conventions.py  # noqa:E501
        self.assertFalse(only_hex_pairs("02015700049C."))  # contains end character  # noqa:E501
        self.assertFalse(only_hex_pairs("0"))  # not a full pair
        self.assertFalse(only_hex_pairs("_02015700049C"))  # contains start character  # noqa:E501
        self.assertFalse(only_hex_pairs("org_product_02015700049C"))  # service name not split  # noqa:E501

    def test_list_type_names(self):
        self.assertEqual(list_type_names({"a": 1, "b": "B"}),
                         ['a: int', 'b: str'])
        self.assertEqual(list_type_names([1, "b"]), ['int', 'str'])

    def test_list_type_names_fail(self):
        # These types make no sense to use
        #   (Use emit_cast instead for non-collections
        #   or to debug collections as one string)
        with self.assertRaises(TypeError):
            list_type_names("hello")

        with self.assertRaises(TypeError):
            list_type_names(b"\x00")  # bytes

        with self.assertRaises(TypeError):
            list_type_names(bytearray("hello".encode("utf-8")))

        with self.assertRaises(TypeError):
            list_type_names(1)

    def test_emit_cast(self):
        self.assertEqual(emit_cast(1), "int(1)")

    def test_precise_sleep(self):
        start = time.perf_counter()
        openlcb.precise_sleep(0.2)
        # NOTE: Using .3 in both assertions below only asserts accuracy
        #   down to 100ms increments (when using the values .2 then .1),
        #   though OS-level calls (used internally in precise_sleep) are
        #   probably far more accurate (though that may depend on the OS
        #   and scenario).
        self.assertLess(
            time.perf_counter() - start,
            .3
        )
        openlcb.precise_sleep(0.1)
        self.assertGreaterEqual(
            time.perf_counter() - start,
            .3
        )

    def test_formatted_ex(self):
        self.assertEqual(
            formatted_ex(ValueError("hello")),
            "ValueError: hello"
        )


if __name__ == '__main__':
    unittest.main()
