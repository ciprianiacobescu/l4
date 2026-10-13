import unittest

from greeter import farewell


class FarewellTests(unittest.TestCase):
    def test_l4_c_49a0a655_named_farewell(self):
        self.assertEqual(farewell("Ada"), "Goodbye, Ada!")
