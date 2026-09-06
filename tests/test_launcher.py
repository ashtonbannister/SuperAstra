"""Regression checks for BizHawk's filename-free 'main' Lua chunk."""
from pathlib import Path
import unittest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    def run_launcher(self, chunk_name, existing_path):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.globals().existing_path = existing_path
        lua.execute('''
          io.open=function(path, mode)
            checked_path=path
            if path==existing_path then return {close=function() closed=true end} end
          end
          dofile=function(path)
            loaded_path=path
            return function(root) launched_root=root end
          end
        ''')
        execute = lua.eval('function(source,name) assert(load(source,name))() end')
        execute((ROOT / "LOAD-IN-BIZHAWK.lua").read_text(), chunk_name)
        return lua.globals()

    def test_bizhawk_main_chunk_uses_script_working_directory(self):
        g = self.run_launcher("main", "./emulator/bizhawk.lua")
        self.assertEqual(g.launched_root, ".")
        self.assertEqual(g.loaded_path, "./emulator/bizhawk.lua")
        self.assertTrue(g.closed)

    def test_absolute_windows_path_with_spaces(self):
        folder = r"C:\Users\Player One\Downloads\Astra-SNES"
        g = self.run_launcher("@" + folder + r"\LOAD-IN-BIZHAWK.lua", folder + "/emulator/bizhawk.lua")
        self.assertEqual(g.launched_root, folder)

    def test_bare_filename_uses_script_working_directory(self):
        g = self.run_launcher("@LOAD-IN-BIZHAWK.lua", "./emulator/bizhawk.lua")
        self.assertEqual(g.launched_root, ".")

    def test_missing_companion_files_explains_extraction(self):
        with self.assertRaisesRegex(Exception, "Extract the entire ZIP"):
            self.run_launcher("main", "missing")


if __name__ == "__main__":
    unittest.main()
