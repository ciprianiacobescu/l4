import unittest

from greeter import farewell


class FarewellTests(unittest.TestCase):
    def test_l4_c_590ae9d1_farewell_returns_goodbye(self):
        self.assertEqual(farewell("Ada"), "Goodbye, Ada!")
