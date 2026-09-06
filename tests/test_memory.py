import unittest
from astra_snes.memory import Scanner, address
from astra_snes.context import Cartridge


class MemoryTests(unittest.TestCase):
    def test_wram_address_normalization(self):
        self.assertEqual(address("7E0019"), 25)
        self.assertEqual(address("$1FFFF"), 131071)
        self.assertEqual(address("0x7FFFFF"), 131071)
        self.assertEqual(address(25), 25)
        for invalid in ["800000", -1, 131072, True]:
            with self.assertRaises(ValueError): address(invalid)

    def test_scan_refines_and_requires_same_game(self):
        scanner = Scanner()
        ctx = {"session": "s", "romhash": "h", "epoch": 0}
        ram = bytearray(131072); ram[23] = 80; ram[24] = 80
        self.assertEqual(scanner.scan(bytes(ram), ctx, "new", 1, 80)["count"], 2)
        ram[23] = 79
        r = scanner.scan(bytes(ram), ctx, "decreased", 1)
        self.assertEqual(r["count"], 1)
        self.assertEqual(r["candidates"][0]["address"], "7E0017")
        with self.assertRaises(ValueError): scanner.scan(bytes(ram), dict(ctx, epoch=1), "changed", 1)

    def test_scan_includes_unaligned_multibyte_and_end(self):
        scanner = Scanner(); ctx = {"session": "s", "romhash": "h", "epoch": 0}
        ram = bytearray(131072); ram[-3:] = bytes([0x56, 0x34, 0x12])
        r = scanner.scan(bytes(ram), ctx, "new", 3, 0x123456)
        self.assertEqual(r["candidates"], [{"address": "7FFFFD", "value": 0x123456}])

    def test_cartridge_search_overlapping(self):
        c = Cartridge(b"aaaabbb")
        self.assertEqual(c.search("61 61")["file_offsets"], ["000000", "000001", "000002"])
        with self.assertRaises(ValueError): c.read(6, 2)


if __name__ == "__main__":
    unittest.main()
