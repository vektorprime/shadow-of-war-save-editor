"""
Shadow of War Save File - Gear Unequip Tool
Fixes save files where equipped gear causes the game to crash.

Usage: python fix_gear.py <savefile.sav> <steam_id_hex> [--iuc-only] [--dry-run]
Example: python fix_gear.py 0b784430_ShadowOfWar.sav 0x0b784430
"""
import struct
import sys
import shutil
from Crypto.Cipher import AES

RAW_KEY = "ad@210766@vac94Cd_?dVt5$alivjz$e"
RAW_IV = "yuwgb@oftv@gx$t3"
HEADER_FORMAT = "<4s4s4s4s"
HEADER_SIZE = 16

def construct_key(set_data, key_value):
    """Construct AES-256 key from set_data and key_value."""
    new_key = bytearray(RAW_KEY.encode())
    key_positions = [(11, 1), (26, 0), (17, 3), (18, 2)]
    for pos, idx in key_positions:
        new_key[pos] = set_data[idx]
    version_bytes = [(key_value >> shift) & 0xFF for shift in (24, 16, 8, 0)]
    key_mapping = [(30, 2), (10, 3), (2, 0), (22, 1)]
    for pos, idx in key_mapping:
        new_key[pos] = version_bytes[idx]
    return bytes(new_key)


def decrypt_save(filepath, key_value):
    with open(filepath, "rb") as f:
        data = f.read()
    if len(data) < HEADER_SIZE:
        raise ValueError("File too small")
    
    header = data[:HEADER_SIZE]
    encrypted = data[HEADER_SIZE:]
    magic, key_data, file_len, decrypted_len = struct.unpack(HEADER_FORMAT, header)
    
    if magic != b"SOM3":
        raise ValueError(f"Invalid magic: {magic}, expected SOM3")
    
    key = construct_key(key_data, key_value)
    iv = bytes(RAW_IV, "utf-8")
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = cipher.decrypt(encrypted)
    actual_len = struct.unpack("<I", decrypted_len)[0]
    decrypted = decrypted[:actual_len]
    
    # Convert to bytearray for mutability
    return bytearray(decrypted), key_data


def encrypt_save(decrypted, key_data, key_value):
    """Re-encrypt the save data."""
    key = construct_key(key_data, key_value)
    iv = bytes(RAW_IV, "utf-8")
    cipher = AES.new(key, AES.MODE_CBC, iv)
    
    # Pad to 16-byte boundary
    padded_len = ((len(decrypted) + 15) // 16) * 16
    padded = bytes(decrypted) + b"\x00" * (padded_len - len(decrypted))
    encrypted = cipher.encrypt(padded)
    
    # Reconstruct header
    magic = b"SOM3"
    file_len = struct.pack("<I", len(encrypted))
    dec_len = struct.pack("<I", len(decrypted))
    header = struct.pack(HEADER_FORMAT, magic, key_data, file_len, dec_len)
    
    return header + encrypted


def find_section(data, tag_bytes):
    """Find a tagged section in the decrypted data."""
    pos = data.find(tag_bytes)
    if pos < 0:
        return None, None, None
    version = struct.unpack("<I", data[pos+4:pos+8])[0]
    padded_size = struct.unpack("<I", data[pos+8:pos+12])[0]
    actual_size = struct.unpack("<I", data[pos+16:pos+20])[0]
    data_start = pos + 20
    return pos, data_start, actual_size


def fix_ivgd(data, dry_run=False):
    """Unequip all items in IVGD section by setting byte 7 to 0 for type 0x0202 entries."""
    pos, data_start, actual_size = find_section(data, b"IVGD")
    if pos is None:
        print("IVGD section not found!")
        return 0
    
    ivgd_data = data[data_start:data_start + actual_size]
    header_end = 0x15  # from observation
    offset = header_end
    fixed = 0
    total = 0
    
    while offset + 9 <= len(ivgd_data):
        itype = struct.unpack("<H", ivgd_data[offset+4:offset+6])[0]
        
        # Known IVGD entry types and their sizes:
        # 0x0202: 9-byte gear entries (slot at byte 6, equipped at byte 7)
        # 0x0102: 12-byte entries (equipped at byte 7)
        # 0x0002: 12-byte entries (equipped at byte 7)
        if itype == 0x0202:
            entry_size = 9
        elif itype in (0x0102, 0x0002):
            entry_size = 12
        else:
            # Unknown type - skip one byte and try again
            offset += 1
            continue
        
        total += 1
        eq_pos = data_start + offset + 7
        if data[eq_pos] == 1:
            if not dry_run:
                data[eq_pos] = 0
            fixed += 1
        offset += entry_size
    
    print(f"IVGD: {total} entries scanned, {fixed} items unequipped")
    return fixed


def fix_iuc(data, dry_run=False):
    """Unequip all items in IIUC section.
    
    IIUC entries are 7 bytes: [4 bytes ID][1 byte slot][1 byte equipped][1 byte pad]
    First 6 bytes after header are section metadata.
    """
    pos, data_start, actual_size = find_section(data, b"IIUC")
    if pos is None:
        print("IIUC section not found!")
        return 0
    
    iuc_data = data[data_start:data_start + actual_size]
    
    # The first 6 bytes are a sub-header
    entry_start = 6
    entry_size = 7
    
    offset = entry_start
    fixed = 0
    total = 0
    
    while offset + entry_size <= len(iuc_data):
        total += 1
        eq_pos = data_start + offset + 5  # byte 5 is equipped flag
        eq_val = data[eq_pos]
        if eq_val == 1:
            if not dry_run:
                data[eq_pos] = 0
            fixed += 1
        offset += entry_size
    
    print(f"IIUC: {total} entries scanned, {fixed} items unequipped")
    return fixed


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    
    filepath = sys.argv[1]
    key_value = int(sys.argv[2], 16)
    dry_run = "--dry-run" in sys.argv
    iuc_only = "--iuc-only" in sys.argv
    
    # Create backup
    backup_path = filepath + ".backup"
    if not dry_run:
        shutil.copy2(filepath, backup_path)
        print(f"Backup created: {backup_path}")
    
    # Decrypt
    print(f"\nDecrypting {filepath}...")
    decrypted, key_data = decrypt_save(filepath, key_value)
    print(f"Decrypted: {len(decrypted)} bytes")
    
    # Fix
    mode = "DRY RUN" if dry_run else "FIXING"
    print(f"\n--- {mode} ---")
    
    if not iuc_only:
        fix_ivgd(decrypted, dry_run)
    fix_iuc(decrypted, dry_run)
    
    if dry_run:
        print("\nDry run complete. No changes made.")
        return
    
    # Re-encrypt
    print(f"\nRe-encrypting...")
    encrypted_data = encrypt_save(decrypted, key_data, key_value)
    
    # Write output
    output_path = filepath.replace(".sav", "_FIXED.sav")
    if output_path == filepath:
        output_path = filepath + ".fixed"
    with open(output_path, "wb") as f:
        f.write(encrypted_data)
    
    print(f"Fixed save written to: {output_path}")
    print(f"Size: {len(encrypted_data)} bytes")
    print(f"\nTo use: Replace your original save file with this one.")
    print(f"  Rename: {output_path} -> {filepath}")


if __name__ == "__main__":
    main()
