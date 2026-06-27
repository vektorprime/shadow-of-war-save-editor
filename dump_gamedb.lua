-- dump_gamedb.lua — Cheat Engine Lua script
-- Dumps all game database string lists to text files for use by the save editor.
--
-- Usage:
--   1. Open Cheat Engine, attach to ShadowOfWar.exe
--   2. Load this script (Ctrl+Alt+L, or Table > Show Cheat Table Lua Script, paste, Execute)
--   3. Files are written to the same directory as the CT file, under gamedb_dump/
--
-- Requires: Cheat Engine 6.7+ with game running

local OUTPUT_DIR = getCheatEngineDir() .. [[gamedb_dump\]]
os.execute('mkdir "' .. OUTPUT_DIR .. '" 2>nul')

-- ─────────────────────────────────────────────────────────────────────
-- Database pointer resolution (matches CT registerDB functions)
-- ─────────────────────────────────────────────────────────────────────
local p_gamedb = nil

local function try_getAddress(expr)
    local ok, result = pcall(getAddress, expr)
    if ok and result ~= 0 then return result end
    return nil
end

local function registerDB_ns()
    -- Version-specific: v1.0.7636.0 steam (update offset if needed)
    local base = try_getAddress("ShadowOfWar.exe+26CCC38")
    if base then
        base = readPointer(base)
        if base and base ~= 0 then
            return base
        end
    end
    return nil
end

local function registerDB_f1()
    autoAssemble([[
        aobscanmodule(aob_gamedb_dump,ShadowOfWar.exe,00 00 ** ** ** ** ** ** 00 00 64 61 74 61 62 61 73 65 5C 67 61 6D 65 5C 67 61 6D 65 2E 67 61 6D 65 64 62 00)
        registersymbol(aob_gamedb_dump)
    ]])
    local base = try_getAddress("aob_gamedb_dump")
    if base then
        base = readPointer(base + 0x2)
        unregisterSymbol("aob_gamedb_dump")
        if base and base ~= 0 then return base end
    end
    return nil
end

local function registerDB_f2()
    autoAssemble([[
        aobscanmodule(aob_gamedb_dump2,ShadowOfWar.exe,00 ** ** ** ** ** ** 00 00 64 61 74 61 62 61 73 65 5C 67 61 6D 65 5C 67 61 6D 65 2E 67 61 6D 65 64 62 00 00 00 00 00 00 00 00)
        registersymbol(aob_gamedb_dump2)
    ]])
    local base = try_getAddress("aob_gamedb_dump2")
    if base then
        base = readPointer(base + 0x1)
        unregisterSymbol("aob_gamedb_dump2")
        if base and base ~= 0 then return base end
    end
    return nil
end

local function registerDB_s1()
    autoAssemble([[
        aobscan(aob_gamedb_dump3,76 B7 50 25 ** ** ** ** ** ** 00 00)
        registersymbol(aob_gamedb_dump3)
    ]])
    local base = try_getAddress("aob_gamedb_dump3")
    if base then
        base = readPointer(readPointer(base + 0x14) + 0x18)
        unregisterSymbol("aob_gamedb_dump3")
        if base and base ~= 0 then return base end
    end
    return nil
end

local function registerDB_s2()
    autoAssemble([[
        aobscan(aob_gamedb_dump4,00 00 ** ** ** ** 76 B7 50 25)
        registersymbol(aob_gamedb_dump4)
    ]])
    local base = try_getAddress("aob_gamedb_dump4")
    if base then
        base = readPointer(readPointer(base + 0x1a) + 0x18)
        unregisterSymbol("aob_gamedb_dump4")
        if base and base ~= 0 then return base end
    end
    return nil
end

-- Try all methods
local function findGameDB()
    local methods = {registerDB_f1, registerDB_f2, registerDB_ns, registerDB_s1, registerDB_s2}
    for _, method in ipairs(methods) do
        local ok, result = pcall(method)
        if ok and result and result ~= 0 then
            return result
        end
    end
    return nil
end

-- ─────────────────────────────────────────────────────────────────────
-- List reading
-- ─────────────────────────────────────────────────────────────────────
-- list_base + 0x00: ptr to name
-- list_base + 0x28: entry count (uint32)
-- list_base + 0x38: ptr to entry array
-- entry + 0x20: ptr to name string
-- entry stride: 0x28

local ENTRY_STRIDE = 0x28
local LIST_STRIDE   = 0x58

local function bytesToHex(addr, size)
    local ok, bytes = pcall(readBytes, addr, size, true)
    if not ok or type(bytes) ~= "table" then return "" end
    local s = ""
    for j = 1, #bytes do
        s = s .. string.format("%02X", bytes[j])
    end
    return s
end

local function readListEntryNames(list_base)
    local names = {}
    local count = readInteger(list_base + 0x28)
    local entries = readPointer(list_base + 0x38)
    if not entries or entries == 0 or count <= 0 or count > 100000 then
        return names
    end

    for i = 0, count - 1 do
        local entry_addr = entries + (i * ENTRY_STRIDE)
        local entry_bytes = bytesToHex(entry_addr, ENTRY_STRIDE)
        local name_ptr = readPointer(entry_addr + 0x20)
        local name = ""
        if name_ptr and name_ptr ~= 0 then
            name = readString(name_ptr, 256) or ""
        end
        names[#names + 1] = {
            index = i,
            address = entry_addr,
            name = name,
            hex = entry_bytes or "",
        }
    end
    return names
end

local function getListName(list_base)
    local name_ptr = readPointer(list_base)
    if name_ptr and name_ptr ~= 0 then
        return readString(name_ptr, 256) or "(unnamed)"
    end
    return "(null)"
end

local function sanitizeFilename(name)
    return name:gsub("[/\\:*?\"<>|]", "_")
end

-- ─────────────────────────────────────────────────────────────────────
-- Dump all lists
-- ─────────────────────────────────────────────────────────────────────
local function dumpAllLists()
    print("Scanning game database lists (0-2999)...")
    local list_count = 0
    local dumped = 0

    for listInd = 0, 2999 do
        local list_base = readPointer(p_gamedb + 0x50 + (listInd * LIST_STRIDE))
        if not list_base or list_base == 0 then
            goto continue
        end

        local list_name = getListName(list_base)
        local count = readInteger(list_base + 0x28)
        if count <= 0 or count > 100000 then
            goto continue
        end

        list_count = list_count + 1

        -- Read all entry names
        local entries = readListEntryNames(list_base)
        if #entries == 0 then
            goto continue
        end

        dumped = dumped + 1

        -- Write to file
        local filename = sanitizeFilename(list_name) .. ".txt"
        local filepath = OUTPUT_DIR .. filename

        local f, err = io.open(filepath, "w")
        if not f then
            print("  ERROR writing " .. filepath .. ": " .. (err or "unknown"))
            goto continue
        end

        f:write("# Shadow of War Game Database Dump\n")
        f:write("# List: " .. list_name .. "\n")
        f:write("# Entry count: " .. #entries .. "\n")
        f:write("# Entry stride: 0x" .. string.format("%X", ENTRY_STRIDE) .. "\n")
        f:write("# Format: address|name|hex_bytes\n")
        f:write("\n")

        for _, entry in ipairs(entries) do
            f:write(string.format("%016X", entry.address))
            f:write("|")
            f:write(entry.name)
            f:write("|")
            f:write(entry.hex)
            f:write("\n")
        end

        f:close()
        print(string.format("  [%3d] %s → %s (%d entries)", listInd, list_name, filename, #entries))

        ::continue::
    end

    print(string.format("\nDone. Scanned %d lists, dumped %d to: %s", list_count, dumped, OUTPUT_DIR))
end

-- ─────────────────────────────────────────────────────────────────────
-- Main
-- ─────────────────────────────────────────────────────────────────────
local function main()
    print("=== Shadow of War Game Database Dumper ===\n")
    print("Looking for game database pointer...")

    local ok, db = pcall(findGameDB)
    if not ok or not db or db == 0 then
        print("ERROR: Could not find game database pointer.")
        print("Make sure ShadowOfWar.exe is running and you are attached to it.")
        print("You may need to update the offset in registerDB_ns().")
        return
    end

    p_gamedb = db
    print(string.format("Game database found at: 0x%X\n", p_gamedb))

    dumpAllLists()

    print("\nAll done! Files written to: " .. OUTPUT_DIR)
    print("Copy the gamedb_dump/ directory to your save editor folder.")
end

local ok, errmsg = pcall(main)
if not ok then
    print("FATAL ERROR: " .. tostring(errmsg))
    print("Debug info: " .. debug.traceback())
end

collectgarbage()
collectgarbage()
