import unittest

from openlcb.memoryservice import MemorySpace


class OpenLCBNetworkTest(unittest.TestCase):
    def setUp(self):
        pass

    def testEnum(self):
        usedValues = set()
        # ensure values are unique:
        for entry in MemorySpace:
            self.assertNotIn(entry.value, usedValues)
            usedValues.add(entry.value)
            # print('{} = {}'.format(entry.name, entry.value))


if __name__ == '__main__':
    unittest.main()
