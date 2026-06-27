# Middle-earth: Shadow of War — Save File Format

## Overview

Shadow of War save files (`.sav`) are **AES-256-CBC encrypted** binary blobs using a
key derived from the user's Steam ID (or `0x00000000` for GOG). The decrypted payload
contains a proprietary chunked serialization format used by Monolith's **Firebird Engine**.

This document is the result of reverse-engineering the save format, comparing working
reference saves against a corrupted save, and building tooling to fix crash-inducing
gear corruption.

---

## 1. Encryption Layer

### 1.1 Algorithm

| Property | Value |
|----------|-------|
| Cipher   | AES-256-CBC |
| IV       | `yuwgb@oftv@gx$t3` (16 bytes, UTF-8) |
| Base key | `ad@210766@vac94Cd_?dVt5$alivjz$e` (31 bytes, UTF-8) |

### 1.2 Key Construction

The 32-byte AES key is built by taking the base key as a `bytearray` and modifying
specific positions with bytes from two sources:

**From the file header's `key_data` field (4 bytes):**

| Key position | key_data index |
|-------------|----------------|
| 11          | 1              |
| 26          | 0              |
| 17          | 3              |
| 18          | 2              |

**From the Steam ID / user key (split into 4 big-endian bytes):**

| Key position | key_byte index |
|-------------|----------------|
| 30          | 2              |
| 10          | 3              |
| 2           | 0              |
| 22          | 1              |

Example key construction in Python:

```python
RAW_KEY = "ad@210766@vac94Cd_?dVt5$alivjz$e"

def construct_key(key_data_4bytes, steam_id_uint32):
    new_key = bytearray(RAW_KEY.encode())
    # Insert key_data bytes
    key_positions = [(11, 1), (26, 0), (17, 3), (18, 2)]
    for pos, idx in key_positions:
        new_key[pos] = key_data_4bytes[idx]
    # Insert Steam ID bytes (big-endian)
    version_bytes = [(steam_id_uint32 >> shift) & 0xFF for shift in (24, 16, 8, 0)]
    key_mapping = [(30, 2), (10, 3), (2, 0), (22, 1)]
    for pos, idx in key_mapping:
        new_key[pos] = version_bytes[idx]
    return bytes(new_key)
```

### 1.3 File Header (16 bytes)

| Offset | Size | Field           | Description |
|--------|------|-----------------|-------------|
| 0x00   | 4    | `magic`         | `SOM3` (0x334D4F53) |
| 0x04   | 4    | `key_data`      | Embedded key material, used in key construction |
| 0x08   | 4    | `file_len`      | Length of encrypted payload (uint32 LE) |
| 0x0C   | 4    | `decrypted_len` | Length of decrypted data after padding removal (uint32 LE) |

All fields are little-endian. The header layout is `<4s4s4s4s` in Python `struct` format.

### 1.4 Decryption Process

```python
from Crypto.Cipher import AES

IV = b"yuwgb@oftv@gx$t3"

def decrypt_save(filepath, steam_id):
    with open(filepath, "rb") as f:
        data = f.read()

    magic, key_data, file_len, decrypted_len = \
        struct.unpack("<4s4s4s4s", data[:16])
    assert magic == b"SOM3"

    key = construct_key(key_data, steam_id)
    cipher = AES.new(key, AES.MODE_CBC, IV)
    decrypted = cipher.decrypt(data[16:])

    actual_len = struct.unpack("<I", decrypted_len)[0]
    return bytearray(decrypted[:actual_len]), key_data
```

### 1.5 Encryption Process

```python
def encrypt_save(decrypted_data, key_data_4bytes, steam_id):
    key = construct_key(key_data_4bytes, steam_id)
    cipher = AES.new(key, AES.MODE_CBC, IV)

    # Pad to 16-byte boundary with zero bytes
    padded_len = ((len(decrypted_data) + 15) // 16) * 16
    padded = bytes(decrypted_data) + b"\x00" * (padded_len - len(decrypted_data))
    encrypted = cipher.encrypt(padded)

    # Reconstruct header (re-use original key_data)
    header = struct.pack("<4s4s4s4s",
        b"SOM3",
        key_data_4bytes,
        struct.pack("<I", len(encrypted)),
        struct.pack("<I", len(decrypted_data)))
    return header + encrypted
```

---

## 2. Chunked Container Format

The decrypted data uses a hierarchical chunk format with **4-character ASCII tags**
(4CC). Each chunk (or "section") acts as a container for sub-chunks and data.

### 2.1 Chunk Header (20 bytes)

| Offset | Size | Field         | Description |
|--------|------|---------------|-------------|
| 0x00   | 4    | `tag`         | 4-character ASCII identifier (e.g. `SAVE`, `IVGD`) |
| 0x04   | 4    | `version`     | Section version (uint32 LE) |
| 0x08   | 4    | `padded_size` | Padded size of data (uint32 LE) |
| 0x0C   | 4    | `reserved`    | Always 0x00000000 |
| 0x10   | 4    | `actual_size` | Actual data size (uint32 LE) |

The data payload follows immediately after the 20-byte header and has length
`actual_size`. The `padded_size` is `actual_size` rounded up, though typically
they are very close (difference of 0–4 bytes).

### 2.2 Internal Section Header

Most section data payloads begin with an internal sub-header:

| Offset | Size | Description |
|--------|------|-------------|
| 0x00   | 2    | Type marker lo (e.g. 0x04) |
| 0x02   | 2    | Type marker hi (e.g. 0x03) |
| 0x04   | 2    | Padding (0x0000) |
| 0x06   | 4    | Hash/GUID (uint32 LE, e.g. `0x88f675a1`) |
| 0x0A   | varies | Remaining header depends on section type |

---

## 3. Identified Sections

Annotated hex dump of section boundaries found in a typical save file:

```
Offset       Tag    Version  PaddedSz ActualSz
0x00000000   SAVE   2        0x186157 0x186157   Root container (entire save)
0x0000001C   GOXC   5        0x0585   0x0581     Graphics Object Config
0x000005B1   PERF   6        ...      ...        Performance settings
0x00000866   PICB   8        ...      ...        Unknown
0x000008A9   GPDC   5        ...      ...        Game Play Data Container
0x0000159D   GMSC   5        ...      ...        Game Misc Config
0x000015C6   SAVE   31       0x33     0x2F       Sub-save container (player data)
0x0000160D   IVGD   3        0x3EB8   0x3EB4     Inventory/Gear Data (items)
0x000054D5   ENT2   3        0x27     0x23       Entity container
0x0000550C   IVSH   1        0x09     0x05       Inventory sheet header
0x00005525   PPDC   3        0x63     0x5F       Player Property Data Container
0x0000558C   PDIC   9        0x29E8   0x29E4     Player Data/Inventory/Character
0x00007F90   PAIC   1        ...      ...        Unknown
0x00008021   IEUC   1        ...      ...        Unknown
0x00008058   IVMG   43       ...      ...        Unknown
0x0000D137   IVPD   4        ...      ...        Unknown
0x0000E19A   TTRL   10       ...      ...        Unknown
0x0000E5A8   LTMR   1        ...      ...        Unknown
...
0x000DDF19   AUDI   1        0x0522   0x051E     Audio data
0x000DE44B   IIUC   48       0x0CD7   0x0CD3     Item Inventory User Content
0x000DF132   UITC   3        0x1F     0x1B       UI Table Content
0x000DF161   STOR   159      0x0C6C   0x0C68     Store/Storage
0x00185F3F   LPDC   4        ...      ...        Unknown
0x0018610B   ...    (end of file)
```

---

## 4. IVGD — Inventory / Gear Data

IVGD is the primary item instance store. Every gear item that exists in the game
world (player inventory, orc equipment, world drops) has an entry here.

### 4.1 Section Header

After the 20-byte chunk header, the IVGD data starts with a sub-header:

| Offset (IVGD data) | Size | Value observed | Description |
|---------------------|------|----------------|-------------|
| 0x00                | 2    | `0x04`         | Marker |
| 0x02                | 2    | `0x03`         | Sub-type |
| 0x04                | 2    | `0x0000`       | Padding |
| 0x06                | 4    | `0x88F675A1`   | Hash/GUID |
| 0x0A                | 4    | varies         | Unknown |
| 0x0E                | 2    | `0x0004`       | Unknown |
| 0x10                | 4    | `0x0000023D`   | Possibly item count (= 573) |
| 0x14                | 1    | `0x00`         | Terminator |

**Item entries begin at IVGD data offset 0x15.**

### 4.2 Item Entry — Type 0x0202 (9 bytes)

This is the most common entry type (>90% of entries).

| Offset | Size | Field      | Description |
|--------|------|------------|-------------|
| 0x00   | 4    | `item_id`  | Item instance ID (uint32 LE, monotonically increasing) |
| 0x04   | 2    | `item_type` | Always `0x0202` (uint16 LE) |
| 0x06   | 1    | `slot`     | Container/category byte (0x0C = general gear, 0x08 = ring/skill) |
| 0x07   | 1    | `equipped` | Active/instantiated flag: `0x01` = active, `0x00` = inactive |
| 0x08   | 1    | `padding`  | Always `0x00` |

Total: **9 bytes per entry**.

### 4.3 Item Entry — Type 0x0102 (12 bytes)

Less common. Has 3 extra bytes compared to 0x0202.

| Offset | Size | Field       | Description |
|--------|------|-------------|-------------|
| 0x00   | 4    | `item_id`   | Item instance ID (uint32 LE) |
| 0x04   | 2    | `item_type` | `0x0102` (uint16 LE) |
| 0x06   | 1    | `slot`      | Container/category (typically `0x08`) |
| 0x07   | 1    | `equipped`  | Active flag |
| 0x08   | 5    | `extra`     | Additional data (usually zeros) |

Total: **12 bytes per entry**.

### 4.4 Item Entry — Type 0x0002 (12 bytes)

Rarest variant. Only appears in corrupted/modified saves.

| Offset | Size | Field       | Description |
|--------|------|-------------|-------------|
| 0x00   | 4    | `item_id`   | Item instance ID (uint32 LE) |
| 0x04   | 2    | `item_type` | `0x0002` (uint16 LE) |
| 0x06   | 1    | `slot`      | Container/category (may be `0x0A` in corrupted saves) |
| 0x07   | 1    | `equipped`  | Active flag |
| 0x08   | 5    | `extra`     | Additional data (usually zeros) |

Total: **12 bytes per entry**.

### 4.5 IVGD Parsing Algorithm

```python
def parse_ivgd(ivgd_data):
    """Parse all item entries from IVGD section data."""
    pos = 0x15  # entries start after sub-header
    entries = []

    while pos + 9 <= len(ivgd_data):
        item_id = struct.unpack("<I", ivgd_data[pos:pos+4])[0]
        item_type = struct.unpack("<H", ivgd_data[pos+4:pos+6])[0]

        if item_type == 0x0202:
            entry_size = 9
        elif item_type in (0x0102, 0x0002):
            entry_size = 12
        else:
            pos += 1  # skip unknown byte and retry
            continue

        slot = ivgd_data[pos+6]
        equipped = ivgd_data[pos+7]

        entries.append({
            'offset': pos,
            'item_id': item_id,
            'type': item_type,
            'slot': slot,
            'equipped': equipped,
            'size': entry_size
        })
        pos += entry_size

    return entries
```

### 4.6 Slot Value Distribution

Observed across multiple save files:

| Slot byte | Description | Reference saves | Corrupted save |
|-----------|-------------|-----------------|----------------|
| 0x0C      | General gear container | 376 items | 1,539 items |
| 0x08      | Ring/skill items | 41 items | 135 items |
| 0x0A      | Unknown (rare) | 11 items | 42 items |
| 0x00      | Null/unused | 0 | 2 items |

### 4.7 Equipped Flag Semantics

The `equipped` byte (`byte 7`) does **not** solely mean "player is wearing this item."
Based on cross-referencing working saves, it indicates **"item is active/instantiated
in the game world."** A working late-game save has ~156 "active" items across all
slots, which far exceeds the 6 player equipment slots.

The **IIUC section** (see §5) is the more likely candidate for tracking which
specific items are in the player's equipment loadout.

---

## 5. IIUC — Item Inventory User Content

IIUC appears to track item **usage state**, possibly including which items are in
the player's active loadout (equipped gear + upgrade/challenge slots).

### 5.1 Section Header

After the 20-byte chunk header, IIUC data has a 6-byte sub-header:

| Offset (IIUC data) | Size | Value observed | Description |
|---------------------|------|----------------|-------------|
| 0x00                | 2    | `0x1004`       | Marker |
| 0x02                | 4    | `0x00000000`   | Padding |

**Item entries begin at IIUC data offset 0x06.**

### 5.2 Item Entry (7 bytes)

| Offset | Size | Field       | Description |
|--------|------|-------------|-------------|
| 0x00   | 4    | `item_id`   | Item reference ID (uint32 LE) — different namespace from IVGD |
| 0x04   | 1    | `slot`      | Category (always `0x0C` in first block) |
| 0x05   | 1    | `equipped`  | Active/in-use flag: `0x01` = active, `0x00` = not |
| 0x06   | 1    | `padding`   | Always `0x00` |

Total: **7 bytes per entry**.

### 5.3 Group-of-Three Structure

IIUC entries are organized in **groups of 3 sequential IDs**. Each group likely
represents a single equipment piece with two associated upgrade/challenge slots:

```
Group 1: 0x07499A42, 0x07499A43, 0x07499A44  (3 equipped in late game)
Group 2: 0x0BA13795, 0x0BA13796, 0x0BA13797  (3 equipped in late game)
Group 3: 0x0BEF32D7, 0x0BEF32D8, 0x0BEF32D9  (3 equipped in late game)
Group 4: 0x0E2B812B, 0x0E2B812C, 0x0E2B812D  (3 equipped in late game)
Group 5: 0xC38D62D3, 0xC38D62D4, 0xC38D62D5  (3 equipped in late game)
```

5 groups x 3 entries = 15 active entries in a fully-equipped late game save.
This maps to 5 equipment pieces (Sword, Dagger, Bow, Armor, Cloak), with the
Ring possibly tracked elsewhere or as a 6th group not yet unlocked.

### 5.4 IIUC Parsing Algorithm

```python
def parse_iuc(iuc_data):
    """Parse entries from IIUC section data. Stops on malformed entries."""
    pos = 0x06  # entries start after 6-byte sub-header
    entry_size = 7
    entries = []

    while pos + entry_size <= len(iuc_data):
        item_id = struct.unpack("<I", iuc_data[pos:pos+4])[0]
        slot = iuc_data[pos+4]
        equipped = iuc_data[pos+5]

        # Sanity checks — stop on garbage data
        if item_id == 0xFFFFFFFF and not (slot == 0 and equipped == 0):
            break
        if slot > 0x20 and slot != 0xFF:
            break

        entries.append({
            'offset': pos,
            'item_id': item_id,
            'slot': slot,
            'equipped': equipped
        })
        pos += entry_size

    return entries
```

### 5.5 IIUC vs IVGD

| Property | IVGD | IIUC |
|----------|------|------|
| Entry size | 9 or 12 bytes | 7 bytes (first block) |
| ID namespace | Low-to-high sequential instance IDs | Higher ID range, different namespace |
| Purpose | All item instances in game world | Item usage/equip loadout state |
| Equipped meaning | "Active in world" | "In player loadout" |
| Count in working save | 428 entries | 21 entries (7 groups of 3) |
| Growth across saves | ~96 → ~156 equipped | ~3 → ~15 equipped |

---

## 6. Cross-Save Analysis: Healthy vs Corrupted

Three saves were compared to identify corruption patterns:

### 6.1 Data Summary

| Metric | Reference Early (Save 2) | Reference Late (Save 51) | User Save (Crashing) |
|--------|--------------------------|--------------------------|----------------------|
| Decrypted size | 568,259 bytes | 1,115,748 bytes | 1,632,910 bytes |
| IVGD items | 428 | 428 | 1,718 |
| IVGD equipped | 94 | 156 | 296 |
| IIUC entries | 21 | 21 | 21 |
| IIUC equipped | 3 | 15 | 5 |
| Slot 0x0C items | 376 | 376 | 1,539 |
| Slot 0x08 items | 41 | 41 | 135 |
| Slot 0x0A items | 11 | 11 | 42 |
| Slot 0x00 items | 0 | 0 | 2 |
| Type 0x0002 items | 0 | 0 | 1+ |
| Duplicate IDs | None | None | Many (IDs repeat 2-3x) |

### 6.2 Key Findings

1. **Working saves have exactly 428 IVGD items regardless of progress.** The item count
   is fixed — game progression changes which ones are active, not the total count.

2. **The corrupted save has 1,718 items (4x normal).** These 1,290 extra entries are
   almost certainly from Cheat Engine / mod duplication. Many are identical copies
   of the same item ID appearing as separate entries.

3. **The corrupted save has a slot 0x0A entry with type 0x0002** (`ID=0x544E0BE0`).
   Type 0x0002 does not appear in any working save and is highly suspicious.

4. **The corrupted save has 2 slot 0x00 entries** — these do not appear in any
   working save.

5. **The corrupted save has 296 equipped IVGD items vs 156 max in working saves.**
   Many are duplicate IDs marked equipped multiple times, which the game engine
   likely cannot handle.

6. **IIUC is consistent at 21 entries across all saves**, confirming this section
   has a fixed structure. The number of equipped entries scales with game progress
   (3 in early game, 15 in late game).

### 6.3 Crash Theory

The crash is caused by one or more of:
- An item entry with an invalid type/slot combination (e.g. type 0x0002, slot 0x0A)
- Multiple IVGD entries sharing the same item ID with the equipped flag set
- The engine encountering 296 "active" items when it expects at most ~156
- A specific corrupted item property in the PDIC section that references an
  invalid IVGD entry

---

## 7. Other Notable Sections

### 7.1 PPDC — Player Property Data Container

Small section (~99 bytes). Contains references linking player data to entity IDs.
Format uses nested tagged references:

```
04 [4-byte reference] [4-byte value] [4-byte count] [additional data...]
```

Observed repeating pattern:
```
04 1C 00 00 00 04 BE 39 00 00 04 01 00 00 00 00 35 1B 66 0E
```

- `0x04` = type marker
- Following 4 bytes = a reference/target ID
- `0x04` = another marker
- Following 4 bytes = another reference
- `0x04 0x01 0x00 0x00 0x00 0x00` = count/value
- `0x35 0x1B 0x66 0x0E` = hash/identifier

### 7.2 PDIC — Player Data Inventory Character

Large section (10,728 bytes in working save). Contains nested property containers
with character-level data (stats, skills, equipment loadout references). Each
entry appears to follow:

```
04 [4-byte property_hash] [4-byte value_count] [4-byte flags] [4-byte target_ref]
```

Entries are iterated with:
```
04 03 00 00 00 00 EA 57 9C 01 04 07 00 00 00 00 FF 9E 17 02 04 00 00 00 00 00 ...
```

Where `0x04` marks the start of each property, the next 2 bytes are a type
indicator, and the remaining bytes encode the property value.

### 7.3 STOR — Store / Storage

~3,180 bytes. Contains storage/inventory references:

```
04 [4-byte reference] 04 00 00 00 00 0C 00 04 [slot_type] 00 00 04 [4-byte ID] 04 00 00 00 00 ...
```

Tracks which items are available in storage/chests.

### 7.4 AUDI — Audio Data

Contains 32-bit identifiers (likely sound/resource hashes):

```
04 XX XX XX XX 04 XX XX XX XX 04 XX XX XX XX ...
```

### 7.5 Root SAVE Container

The outermost chunk (`SAVE` version 2) wraps the entire decrypted payload.
Inside it are:

- `GOXC` (Graphics Object Configuration)
- Performance settings (`PERF`, `PICB`)
- Game state configurations (`GPDC`, `GMSC`)
- A nested `SAVE` container (version 31) that holds player data:
  - `IVGD` — Inventory/Gear Data (all item instances)
  - `ENT2` — Entities (2 entries, likely character/bodyguard refs)
  - `IVSH` — Inventory Sheet Header
  - `PPDC` — Player Property Data Container
  - `PDIC` — Player Data/Inventory/Character
  - `PAIC`, `IEUC`, `IVMG`, `IVPD` — Various player state sections
- Additional top-level sections: `TTRL`, `LTMR`, `AUDI`, `IIUC`, `UITC`, `STOR`, `LPDC`

---

## 8. Gear Name Database

The editor includes a database of **84 named gear items** spanning all known
legendary sets. Items are organized by equipment slot:

### 8.1 Equipment Slots and Item Counts

| Slot   | Count | Examples |
|--------|-------|----------|
| Sword  | 14    | Urfael (Default), Bright Lord's Sword, Sword of Vengeance, Sword of War... |
| Dagger | 14    | Acharn (Default), Bright Lord's Dagger, Dagger of Vengeance... |
| Bow    | 14    | Azkar (Default), Bright Lord's Bow, Hammer of Horrors, Bow of Beasts... |
| Armor  | 14    | Ranger Armor (Default), Bright Lord's Armor, Armor of War... |
| Cloak  | 14    | Ranger Cloak (Default), Bright Lord's Cloak, Cloak of Vengeance... |
| Ring   | 14    | New Ring (Default), Bright Lord's Rune, Rune of Horrors... |

### 8.2 Legendary Sets Covered

| Set | Description |
|-----|-------------|
| **Bright Lord** | Ithildin door rewards (endgame) |
| **Vendetta** | Online vendetta mission drops |
| **Dark** | Legendary Dark tribe orc drops |
| **Feral** | Legendary Feral tribe orc drops |
| **Machine** | Legendary Machine tribe orc drops |
| **Marauder** | Legendary Marauder tribe orc drops |
| **Mystic** | Legendary Mystic tribe orc drops |
| **Terror** | Legendary Terror tribe orc drops |
| **Warmonger** | Legendary Warmonger tribe orc drops |
| **Slaughter** | Slaughter tribe DLC orc drops |
| **Outlaw** | Outlaw tribe DLC orc drops |
| **Ringwraith** | Nazgul/ringwraith related gear |
| **Default** | Starter gear (Urfael, Acharn, Azkar, Ranger set, New Ring) |

---

## 9. Complete Decrypt → Modify → Encrypt Workflow

```python
import struct
from Crypto.Cipher import AES

RAW_KEY = "ad@210766@vac94Cd_?dVt5$alivjz$e"
RAW_IV  = "yuwgb@oftv@gx$t3"

def construct_key(key_data, steam_id):
    """Build 32-byte AES key from header key_data and Steam ID."""
    new_key = bytearray(RAW_KEY.encode())
    for pos, idx in [(11, 1), (26, 0), (17, 3), (18, 2)]:
        new_key[pos] = key_data[idx]
    ver = [(steam_id >> s) & 0xFF for s in (24, 16, 8, 0)]
    for pos, idx in [(30, 2), (10, 3), (2, 0), (22, 1)]:
        new_key[pos] = ver[idx]
    return bytes(new_key)

def decrypt(filepath, steam_id):
    with open(filepath, "rb") as f:
        data = f.read()
    magic, key_data, enc_len, dec_len = struct.unpack("<4s4s4s4s", data[:16])
    key = construct_key(key_data, steam_id)
    cipher = AES.new(key, AES.MODE_CBC, RAW_IV.encode())
    decrypted = cipher.decrypt(data[16:])
    return bytearray(decrypted[:struct.unpack("<I", dec_len)[0]]), key_data

def encrypt(decrypted, key_data, steam_id):
    key = construct_key(key_data, steam_id)
    cipher = AES.new(key, AES.MODE_CBC, RAW_IV.encode())
    pad = ((len(decrypted) + 15) // 16) * 16
    padded = bytes(decrypted) + b"\x00" * (pad - len(decrypted))
    enc = cipher.encrypt(padded)
    return struct.pack("<4s4s4s4s", b"SOM3", key_data,
                       struct.pack("<I", len(enc)),
                       struct.pack("<I", len(decrypted))) + enc

def find_section(data, tag_bytes):
    """Locate a tagged section; returns (chunk_offset, data_start, actual_size)."""
    pos = data.find(tag_bytes)
    if pos < 0: return None, None, None
    actual = struct.unpack("<I", data[pos+16:pos+20])[0]
    return pos, pos + 20, actual

def fix_gear_ivgd(data, dry_run=False):
    """Set all equipped flags (byte 7) to 0 for IVGD entries."""
    _, start, size = find_section(data, b"IVGD")
    if start is None: return 0
    ivgd = data[start:start + size]
    pos, fixed, total = 0x15, 0, 0
    while pos + 9 <= len(ivgd):
        t = struct.unpack("<H", ivgd[pos+4:pos+6])[0]
        if t == 0x0202: es = 9
        elif t in (0x0102, 0x0002): es = 12
        else: pos += 1; continue
        total += 1
        eq_pos = start + pos + 7
        if data[eq_pos] == 1:
            if not dry_run: data[eq_pos] = 0
            fixed += 1
        pos += es
    return fixed

def fix_gear_iuc(data, dry_run=False):
    """Set all equipped flags (byte 5) to 0 for IIUC entries."""
    _, start, size = find_section(data, b"IIUC")
    if start is None: return 0
    iuc = data[start:start + size]
    pos, fixed, total = 0x06, 0, 0
    while pos + 7 <= len(iuc):
        total += 1
        eq_pos = start + pos + 5
        if data[eq_pos] == 1:
            if not dry_run: data[eq_pos] = 0
            fixed += 1
        pos += 7
    return fixed

# Usage:
# data, key_data = decrypt("0b784430_ShadowOfWar.sav", 0x0b784430)
# fix_gear_ivgd(data)
# fix_gear_iuc(data)
# fixed = encrypt(data, key_data, 0x0b784430)
# with open("0b784430_ShadowOfWar_FIXED.sav", "wb") as f: f.write(fixed)
```

---

## 10. Steam ID / Filename Convention

- Steam saves are named `XXXXXXXX_ShadowOfWar.sav` where `XXXXXXXX` is the 8-hex-digit
  Steam ID (e.g. `0b784430` → `0x0B784430` = 192,431,152 decimal).
- GOG saves use `0x00000000` as the key and have the computer name as prefix.
- The Steam ID is used both in key construction and in the filename.
- Saves are bound to the Steam account; cross-account usage requires
  decrypting with the original key and re-encrypting with the new one.
- The reference save pack (Nexus Mods mod/129) uses Steam ID `0x1C2CE90C`.

---

## 11. Tools

### 11.1 Slot-Based GUI Editor (`sow_slot_editor.py`)

Location: `C:\Users\vicha\AppData\Local\Temp\opencode\sow_slot_editor.py`

A tkinter GUI with two tabs:

**Equipment Tab:**
- Shows 6 equipment slots (Sword, Dagger, Bow, Armor, Cloak, Ring)
- Each slot has a dropdown of 14 named gear items
- "Apply All Changes" writes selections to the decrypted save buffer
- "Clear All" removes all slot assignments
- Current equipment status shown next to each dropdown

**All Items Tab:**
- Raw IVGD item list with filter (All, Equipped Only, by slot, by type)
- Shows item ID, type, slot byte, and equipped status

**Features:**
- Auto-detects Steam ID from filename
- Auto-creates `.sav.backup` on first open
- File > Open / Save / Save As with standard dialogs
- Tools > Unequip All Gear (bulk clear)
- Tools > Load Reference Save (load a working save for comparison)
- Round-trip encryption verified (decrypt → modify → encrypt produces identical-sized output)

**Usage:**
```powershell
python sow_slot_editor.py "path\to\XXXXXXXX_ShadowOfWar.sav"
```

### 11.2 CLI Fix Script (`fix_gear.py`)

Location: `C:\Users\vicha\AppData\Local\Temp\opencode\fix_gear.py`

Command-line tool that unequips all items in IVGD and IIUC sections.
Use `--dry-run` to preview without writing.

```powershell
python fix_gear.py "savefile.sav" 0xSTEAMID
python fix_gear.py "savefile.sav" 0xSTEAMID --dry-run
```

---

## 12. Limitations & Unknowns

1. **Item type identification**: The `item_id` fields are instance IDs (monotonically
   increasing per save), not static item type hashes. Without the game's item
   database, individual item types (Urfael, Ranger Armor, etc.) cannot be
   identified from the save alone. The editor's named items are informational
   labels only — they don't modify the underlying item type data.

2. **Slot byte mapping**: The `slot` byte (byte 6 in IVGD) uses values `0x0C`,
   `0x08`, `0x0A` but does not directly map to equipment slots (Sword, Dagger, etc.).
   Slot 0x0C is a general gear container holding 376/1,539 items, not a single
   equipment slot. The actual slot-to-item mapping likely lives in PDIC or is
   determined by internal item type data within larger item structures.

3. **IIUC block structure**: Only the first ~21 entries of IIUC are understood.
   After entry 21, the data format changes (likely a different sub-block with its
   own header). The remaining 3,200+ bytes of IIUC are not currently parsed.

4. **PDIC complexity**: The Player Data/Inventory/Character section (10,728 bytes)
   contains nested property containers whose full structure has not been mapped.
   This section almost certainly holds the key to mapping equipment slots to
   specific items.

5. **Equipped flag dual meaning**: In IVGD, `equipped = 1` means "active in world,"
   not "player is wearing." In IIUC, `equipped = 1` likely means "in player loadout."
   Clearing all IVGD equipped flags is a conservative fix that prevents crashes
   but does not address root-cause corruption in other sections.

6. **Item property data**: Item level, rarity, abilities, and upgrade challenge
   progress are stored in sections beyond IVGD/IIUC (likely PDIC or IVPD). These
   sections are not yet editable.

7. **Cross-section integrity**: Modifying IVGD without updating corresponding
   entries in PDIC/PPDC may create inconsistencies. The fix script only touches
   IVGD and IIUC equipped flags, which has been sufficient to prevent crashes
   in tested cases.

---

## 13. References

- **shadow-of-war-save-converter**: [GitHub](https://github.com/SystematicSkid/shadow-of-war-save-converter) — Python tool for decrypting/re-encrypting saves between Steam accounts. Source of the AES key construction algorithm.
- **SeiKur0's Cheat Engine Table**: [Fearless Revolution](https://fearlessrevolution.com/viewtopic.php?t=5132) — CE table for in-memory editing of items, uruks, and game state.
- **ReaperAnon's Mods**: [GitHub](https://github.com/ReaperAnon/Shadow-Of-War-Mods) — DLL mods including item challenge autocomplete.
- **Middle-Earth Mod Loader**: [GitHub](https://github.com/ReaperAnon/Middle-Earth-Mod-Loader) — Plugin loader for Shadow of War.
- **Nexus Mods Save Pack (mod/129)**: [Nexus Mods](https://www.nexusmods.com/middleearthshadowofwar/mods/129) — 50 reference save files at various progress points (used for cross-save analysis).
- **Nexus Mods 100% Save (mod/144)**: [Nexus Mods](https://www.nexusmods.com/middleearthshadowofwar/mods/144) — Complete save with max prestige and all gear.
- **Shadow of War Wiki — Gear**: [Fandom](https://shadowofwar.fandom.com/wiki/Gear) — Gear item database and legendary set information.
- **Shadow of War Wiki — Weapons**: [Fextralife](https://shadowofwar.wiki.fextralife.com/Weapons) — Weapon stats and perk listings.
