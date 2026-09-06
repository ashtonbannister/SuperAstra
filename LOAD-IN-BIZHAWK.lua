-- Start the Python app first. Keep this file in the extracted Astra-SNES folder.
-- BizHawk can load scripts as a chunk called "main", without an @filename.
-- Its Lua sandbox sets the working directory to the script's own directory.
local source = debug.getinfo(1, "S").source or ""
local root = source:sub(1, 1) == "@" and source:sub(2):match("^(.*)[/\\]") or "."
local probe = io.open(root .. "/emulator/bizhawk.lua", "rb")
assert(probe, "Astra SNES files were not found. Extract the entire ZIP, keep LOAD-IN-BIZHAWK.lua beside the emulator folder, and open that file in the Lua Console.")
probe:close()
dofile(root .. "/emulator/bizhawk.lua")(root)
