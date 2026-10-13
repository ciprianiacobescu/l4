import unittest

from greeter import greet


class GreetTests(unittest.TestCase):
    def test_l4_c_8fd7d830_greet_returns_hello(self):
        self.assertEqual(greet("Ada"), "Hello, Ada!")

    def test_l4_c_4e4feccc_blank_name_is_rejected(self):
        with self.assertRaises(ValueError):
            greet("  ")
