import unittest

from openlcb.openlcbnetwork import OpenLCBNetwork


class DispatcherTest(unittest.TestCase):
    def setUp(self):
        pass

    def testEnum(self):
        usedValues = set()
        # ensure values are unique:
        for entry in OpenLCBNetwork.Mode:
            self.assertNotIn(entry.value, usedValues)
            usedValues.add(entry.value)
            # print('{} = {}'.format(entry.name, entry.value))


if __name__ == '__main__':
    unittest.main()
