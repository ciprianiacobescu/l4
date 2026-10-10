import unittest

from greeter import greet


class GreetTests(unittest.TestCase):
    def test_l4_c_9618b9f5_named_greeting(self):
        self.assertEqual(greet("Ada"), "Hello, Ada!")

    def test_l4_c_6057a7e3_blank_name(self):
        with self.assertRaises(ValueError):
            greet("  ")
