"""Analyze reference saves from the Nexus Mods save pack."""
import struct, os, sys
from Crypto.Cipher import AES

RAW_KEY = "ad@210766@vac94Cd_?dVt5$alivjz$e"
RAW_IV = "yuwgb@oftv@gx$t3"
HEADER_FORMAT = "<4s4s4s4s"
HEADER_SIZE = 16

def construct_key(key_data, steam_id):
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
    magic, key_data, enc_len, dec_len = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
    key = construct_key(key_data, steam_id)
    cipher = AES.new(key, AES.MODE_CBC, RAW_IV.encode())
    decrypted = cipher.decrypt(data[HEADER_SIZE:])
    return bytearray(decrypted[:struct.unpack("<I", dec_len)[0]])

def find_section(data, tag):
    pos = data.find(tag)
    if pos < 0: return None, None, None
    actual = struct.unpack("<I", data[pos+16:pos+20])[0]
    return pos, pos + 20, actual

def parse_ivgd(data):
    _, start, size = find_section(data, b"IVGD")
    if start is None: return []
    ivgd = data[start:start + size]
    items = []
    pos = 0x15
    while pos + 9 <= len(ivgd):
        itype = struct.unpack("<H", ivgd[pos+4:pos+6])[0]
        if itype == 0x0202: es = 9
        elif itype in (0x0102, 0x0002): es = 12
        else: pos += 1; continue
        items.append({
            "id": struct.unpack("<I", ivgd[pos:pos+4])[0],
            "type": itype, "slot": ivgd[pos+6], "eq": ivgd[pos+7]
        })
        pos += es
    return items

def parse_iuc(data):
    _, start, size = find_section(data, b"IIUC")
    if start is None: return []
    iuc = data[start:start + size]
    items = []
    pos = 0x06
    while pos + 7 <= len(iuc):
        iid = struct.unpack("<I", iuc[pos:pos+4])[0]
        slot = iuc[pos+4]; eq = iuc[pos+5]
        if iid == 0xFFFFFFFF and not (slot==0 and eq==0): break
        if slot > 0x20 and slot != 0xFF: break
        items.append({"id": iid, "slot": slot, "eq": eq})
        pos += 7
    return items

# Pick early game save (Shadows of the Past) and user's save
base = r"C:\Users\vicha\Downloads\MAIN Middle-Earth - Shadow of War SAVES-129-1-0-1727454420"
ref_dir = os.path.join(base, "Middle-earth Shadow of War Save Game 2 Shadows of the Past", "356190", "remote")
ref_file = os.path.join(ref_dir, "1c2ce90c_ShadowOfWar.sav")
user_file = r"C:\Program Files (x86)\Steam\userdata\192431152\356190\remote\0b784430_ShadowOfWar.sav"

STEAM_ID = 0x1c2ce90c

print("=" * 60)
print("REFERENCE SAVE (early game - Save 2)")
print("=" * 60)
ref = decrypt(ref_file, STEAM_ID)
print(f"Size: {len(ref):,} bytes")

rivgd = parse_ivgd(ref)
riuc = parse_iuc(ref)
print(f"IVGD items: {len(rivgd)}, IIUC items: {len(riuc)}")

# Show slot distribution
from collections import Counter
rb_slots = Counter(i["slot"] for i in rivgd)
print(f"IVGD slot distribution: {dict(rb_slots)}")
eq_ivgd = [i for i in rivgd if i["eq"] == 1]
eq_iuc = [i for i in riuc if i["eq"] == 1]
print(f"Equipped IVGD: {len(eq_ivgd)}, Equipped IIUC: {len(eq_iuc)}")

print("\nAll equipped IVGD items (reference):")
for item in eq_ivgd:
    print(f"  ID=0x{item['id']:08X} slot=0x{item['slot']:02X} type=0x{item['type']:04X}")

print("\nAll equipped IIUC items (reference):")
for item in eq_iuc:
    print(f"  ID=0x{item['id']:08X} slot=0x{item['slot']:02X}")

# Now also check a late-game save
print("\n" + "=" * 60)
print("LATE GAME SAVE (Save 51 - All Story Complete)")
print("=" * 60)
late_dir = os.path.join(base, "Middle-earth Shadow of War Save Game 51 All Story Mission Completed", "356190", "remote")
late_file = os.path.join(late_dir, "1c2ce90c_ShadowOfWar.sav")
late = decrypt(late_file, STEAM_ID)
print(f"Size: {len(late):,} bytes")

livgd = parse_ivgd(late)
liuc = parse_iuc(late)
print(f"IVGD items: {len(livgd)}, IIUC items: {len(liuc)}")
lb_slots = Counter(i["slot"] for i in livgd)
print(f"IVGD slot distribution: {dict(lb_slots)}")
leq_ivgd = [i for i in livgd if i["eq"] == 1]
leq_iuc = [i for i in liuc if i["eq"] == 1]
print(f"Equipped IVGD: {len(leq_ivgd)}, Equipped IIUC: {len(leq_iuc)}")

print("\nAll equipped IVGD items (late game):")
for item in leq_ivgd:
    print(f"  ID=0x{item['id']:08X} slot=0x{item['slot']:02X} type=0x{item['type']:04X}")

print("\nAll equipped IIUC items (late game):")
for item in leq_iuc:
    print(f"  ID=0x{item['id']:08X} slot=0x{item['slot']:02X}")

# Also dump the user's save for comparison
print("\n" + "=" * 60)
print("USER SAVE (crashing)")
print("=" * 60)
user = decrypt(user_file, 0x0b784430)
print(f"Size: {len(user):,} bytes")
uivgd = parse_ivgd(user)
uiuc = parse_iuc(user)
print(f"IVGD items: {len(uivgd)}, IIUC items: {len(uiuc)}")
ub_slots = Counter(i["slot"] for i in uivgd)
print(f"IVGD slot distribution: {dict(ub_slots)}")
ueq_ivgd = [i for i in uivgd if i["eq"] == 1]
ueq_iuc = [i for i in uiuc if i["eq"] == 1]
print(f"Equipped IVGD: {len(ueq_ivgd)}, Equipped IIUC: {len(ueq_iuc)}")

print("\nAll equipped IVGD items (user):")
for item in ueq_ivgd:
    print(f"  ID=0x{item['id']:08X} slot=0x{item['slot']:02X} type=0x{item['type']:04X}")

print("\nAll equipped IIUC items (user):")
for item in ueq_iuc:
    print(f"  ID=0x{item['id']:08X} slot=0x{item['slot']:02X}")
