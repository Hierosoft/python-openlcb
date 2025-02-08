import os
import sys
import unittest

from logging import getLogger
logger = getLogger(__name__)

if __name__ == "__main__":
    # Allow importing repo copy of openlcb if running tests from repo manually.
    TESTS_DIR = os.path.dirname(os.path.realpath(__file__))
    REPO_DIR = os.path.dirname(TESTS_DIR)
    if os.path.isfile(os.path.join(REPO_DIR, "openlcb", "__init__.py")):
        sys.path.insert(0, REPO_DIR)
    else:
        logger.warning(
            "Reverting to installed copy if present (or imports will fail),"
            " since test running from repo but could not find openlcb in {}."
            .format(repr(REPO_DIR)))


from openlcb.tcplink.mdnsconventions import id_from_tcp_service_name


class TestMDNSConventions(unittest.TestCase):
    """Cover mdnsconventions.py
    id_from_tcp_service_name requires hex_to_dotted_lcc_id to
    work which is also covered by test_conventions.py.
    """
    def test_id_from_tcp_service_name(self):
        self.assertIsNone(id_from_tcp_service_name("aaaaa.local."))
        self.assertEqual(id_from_tcp_service_name(
            "bobjacobsen_pythonopenlcb_02015700049C._openlcb-can._tcp.local."),
            "02.01.57.00.04.9C"
        )
        self.assertEqual(id_from_tcp_service_name(
            "pythonopenlcb_02015700049C._openlcb-can._tcp.local."),
            "02.01.57.00.04.9C"
        )
        self.assertEqual(id_from_tcp_service_name(
            "02015700049C._openlcb-can._tcp.local."),
            "02.01.57.00.04.9C"
        )


if __name__ == '__main__':
    unittest.main()
