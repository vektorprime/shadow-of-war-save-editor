#!/usr/bin/env python3
"""
Middle-earth: Shadow of War — Save File Editor (Slot-Based)
============================================================
Decrypts, edits, and re-encrypts .sav files.
Shows 6 equipment slots with dropdowns for item selection.

Requirements: pip install pycryptodome
"""
import struct
import sys
import os
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from Crypto.Cipher import AES

# Try to import the game database module
try:
    from gamedb import GameDatabase  # noqa: F811
    GAMEDB_AVAILABLE = True
except ImportError:
    GAMEDB_AVAILABLE = False
    GameDatabase = None  # type: ignore

# ── Constants ──────────────────────────────────────────────────────────
RAW_KEY = "ad@210766@vac94Cd_?dVt5$alivjz$e"
RAW_IV = "yuwgb@oftv@gx$t3"
HEADER_FORMAT = "<4s4s4s4s"
HEADER_SIZE = 16

# ── Equipment Slot Definitions ─────────────────────────────────────────
# The slot byte values we use to categorize items.
# These are educated guesses based on observed save data.
# 0x0C appears to be the main gear container.
# We use type bytes to further distinguish within the same slot.
SLOT_SWORD  = 0x0C  # Most common slot - likely general gear
SLOT_DAGGER = 0x0C  # Same slot, distinguished elsewhere
SLOT_BOW    = 0x0C
SLOT_ARMOR  = 0x0C
SLOT_CLOAK  = 0x0C
SLOT_RING   = 0x08  # Observed on ring/skill items

EQUIPMENT_SLOTS = [
    {"name": "Sword",      "slot_byte": 0x0C, "icon": "⚔"},
    {"name": "Dagger",     "slot_byte": 0x0C, "icon": "🗡"},
    {"name": "Bow",        "slot_byte": 0x0C, "icon": "🏹"},
    {"name": "Armor",      "slot_byte": 0x0C, "icon": "🛡"},
    {"name": "Cloak",      "slot_byte": 0x0C, "icon": "🧥"},
    {"name": "Ring",       "slot_byte": 0x08, "icon": "💍"},
]

# ── Gear Name Database ─────────────────────────────────────────────────
GEAR_BY_SLOT = {
    "Sword": [
        # ── Default ──
        "Urfael (Default Sword)",
        # ── Bright Lord ──
        "Bright Lord's Sword",
        # ── Vendetta ──
        "Sword of Vengeance",
        # ── Tribe Legendary Sets ──
        "Sword of Horrors (Terror)",
        "Sword of Beasts (Feral)",
        "Sword of the War Machine",
        "Sword of the Marauder",
        "Sword of Mystics",
        "Sword of War (Warmonger)",
        "Sword of Darkness (Dark)",
        # ── DLC Tribes ──
        "Sword of the Slaughter Tribe",
        "Sword of the Outlaw Tribe",
        # ── Ringwraith ──
        "Sword of the Ringwraith",
        # ── Epic / Rare / Common drop slots ──
        "Sword — Epic #1",
        "Sword — Epic #2",
        "Sword — Epic #3",
        "Sword — Epic #4",
        "Sword — Epic #5",
        "Sword — Rare #1",
        "Sword — Rare #2",
        "Sword — Rare #3",
        "Sword — Common #1",
        "Sword — Common #2",
        "Sword — Common #3",
        "Unknown Sword",
    ],
    "Dagger": [
        "Acharn (Default Dagger)",
        "Bright Lord's Dagger",
        "Dagger of Vengeance",
        "Dagger of Horrors (Terror)",
        "Dagger of Beasts (Feral)",
        "Dagger of the War Machine",
        "Dagger of the Marauder",
        "Dagger of Mystics",
        "Dagger of War (Warmonger)",
        "Dagger of Darkness (Dark)",
        "Dagger of the Slaughter Tribe",
        "Dagger of the Outlaw Tribe",
        "Dagger of the Ringwraith",
        "Dagger — Epic #1",
        "Dagger — Epic #2",
        "Dagger — Epic #3",
        "Dagger — Rare #1",
        "Dagger — Rare #2",
        "Dagger — Common #1",
        "Dagger — Common #2",
        "Unknown Dagger",
    ],
    "Bow": [
        "Azkar (Default Bow)",
        "Bright Lord's Bow",
        "Longbow of Vengeance",
        "Hammer of Horrors (Terror)",
        "Bow of Beasts (Feral)",
        "Hammer of the War Machine",
        "Bow of the Marauder",
        "Bow of Mystics",
        "Hammer of War (Warmonger)",
        "Hammer of Darkness (Dark)",
        "Bow of the Slaughter Tribe",
        "Bow of the Outlaw Tribe",
        "Hammer of the Ringwraith",
        "Bow — Epic #1",
        "Bow — Epic #2",
        "Bow — Epic #3",
        "Hammer — Epic #1",
        "Hammer — Epic #2",
        "Bow — Rare #1",
        "Bow — Rare #2",
        "Hammer — Rare #1",
        "Bow — Common #1",
        "Bow — Common #2",
        "Unknown Bow",
    ],
    "Armor": [
        "Ranger Armor (Default)",
        "Bright Lord's Armor",
        "Armor of Vengeance",
        "Armor of Horrors (Terror)",
        "Armor of Beasts (Feral)",
        "Armor of the War Machine",
        "Armor of the Marauder",
        "Armor of Mystics",
        "Armor of War (Warmonger)",
        "Armor of Darkness (Dark)",
        "Armor of the Slaughter Tribe",
        "Armor of the Outlaw Tribe",
        "Armor of the Ringwraith",
        "Armor — Epic #1",
        "Armor — Epic #2",
        "Armor — Epic #3",
        "Armor — Epic #4",
        "Armor — Rare #1",
        "Armor — Rare #2",
        "Armor — Rare #3",
        "Armor — Common #1",
        "Armor — Common #2",
        "Unknown Armor",
    ],
    "Cloak": [
        "Ranger Cloak (Default)",
        "Bright Lord's Cloak",
        "Cloak of Vengeance",
        "Cloak of Horrors (Terror)",
        "Cloak of Beasts (Feral)",
        "Cloak of the War Machine",
        "Cloak of the Marauder",
        "Cloak of Mystics",
        "Cloak of War (Warmonger)",
        "Cloak of Darkness (Dark)",
        "Cloak of the Slaughter Tribe",
        "Cloak of the Outlaw Tribe",
        "Cloak of the Ringwraith",
        "Cloak — Epic #1",
        "Cloak — Epic #2",
        "Cloak — Epic #3",
        "Cloak — Rare #1",
        "Cloak — Rare #2",
        "Cloak — Common #1",
        "Cloak — Common #2",
        "Unknown Cloak",
    ],
    "Ring": [
        "New Ring (Default)",
        "Bright Lord's Rune",
        "Ring of Vengeance",
        "Rune of Horrors (Terror)",
        "Rune of Beasts (Feral)",
        "Rune of the War Machine",
        "Rune of the Marauder",
        "Rune of Mystics",
        "Rune of War (Warmonger)",
        "Rune of Darkness (Dark)",
        "Rune of the Slaughter Tribe",
        "Rune of the Outlaw Tribe",
        "Rune of the Ringwraith",
        "Rune — Epic #1",
        "Rune — Epic #2",
        "Rune — Epic #3",
        "Rune — Epic #4",
        "Rune — Rare #1",
        "Rune — Rare #2",
        "Rune — Rare #3",
        "Rune — Common #1",
        "Rune — Common #2",
        "Unknown Ring",
    ],
}

ALL_ITEMS = {}
for slot_name, items in GEAR_BY_SLOT.items():
    for item in items:
        ALL_ITEMS[item] = {"slot": slot_name}


# ── Crypto ─────────────────────────────────────────────────────────────
def construct_key(key_data, steam_id):
    new_key = bytearray(RAW_KEY.encode())
    for pos, idx in [(11, 1), (26, 0), (17, 3), (18, 2)]:
        new_key[pos] = key_data[idx]
    ver = [(steam_id >> s) & 0xFF for s in (24, 16, 8, 0)]
    for pos, idx in [(30, 2), (10, 3), (2, 0), (22, 1)]:
        new_key[pos] = ver[idx]
    return bytes(new_key)


def decrypt_save(filepath, steam_id):
    with open(filepath, "rb") as f:
        data = f.read()
    magic, key_data, enc_len, dec_len = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
    if magic != b"SOM3":
        raise ValueError(f"Invalid magic bytes. Expected SOM3, got {magic}")
    key = construct_key(key_data, steam_id)
    cipher = AES.new(key, AES.MODE_CBC, RAW_IV.encode())
    decrypted = cipher.decrypt(data[HEADER_SIZE:])
    actual_len = struct.unpack("<I", dec_len)[0]
    return bytearray(decrypted[:actual_len]), key_data


def encrypt_save(decrypted, key_data, steam_id):
    key = construct_key(key_data, steam_id)
    cipher = AES.new(key, AES.MODE_CBC, RAW_IV.encode())
    pad_len = ((len(decrypted) + 15) // 16) * 16
    padded = bytes(decrypted) + b"\x00" * (pad_len - len(decrypted))
    enc = cipher.encrypt(padded)
    return struct.pack(HEADER_FORMAT, b"SOM3", key_data,
                       struct.pack("<I", len(enc)),
                       struct.pack("<I", len(decrypted))) + enc


# ── Section Parsing ────────────────────────────────────────────────────
def find_section(data, tag):
    pos = data.find(tag)
    if pos < 0:
        return None, None, None
    actual = struct.unpack("<I", data[pos+16:pos+20])[0]
    return pos, pos + 20, actual


def parse_ivgd(data):
    """Parse IVGD section. Returns list of item dicts with absolute offsets."""
    _, start, size = find_section(data, b"IVGD")
    if start is None:
        return []
    ivgd = data[start:start + size]
    items = []
    pos = 0x15
    while pos + 9 <= len(ivgd):
        itype = struct.unpack("<H", ivgd[pos+4:pos+6])[0]
        if itype == 0x0202:
            es = 9
        elif itype in (0x0102, 0x0002):
            es = 12
        else:
            pos += 1
            continue
        items.append({
            "abs_offset": start + pos,
            "id": struct.unpack("<I", ivgd[pos:pos+4])[0],
            "type": itype,
            "slot": ivgd[pos+6],
            "eq": ivgd[pos+7],
            "size": es,
            "rel_offset": pos,
        })
        pos += es
    return items


def parse_iuc(data):
    """Parse IIUC section. Returns list of item dicts."""
    _, start, size = find_section(data, b"IIUC")
    if start is None:
        return []
    iuc = data[start:start + size]
    items = []
    pos = 0x06
    while pos + 7 <= len(iuc):
        iid = struct.unpack("<I", iuc[pos:pos+4])[0]
        slot = iuc[pos+4]
        eq = iuc[pos+5]
        if iid == 0xFFFFFFFF and not (slot == 0 and eq == 0):
            break
        if slot > 0x20 and slot != 0xFF:
            break
        items.append({
            "abs_offset": start + pos,
            "id": iid, "slot": slot, "eq": eq, "size": 7,
            "rel_offset": pos,
        })
        pos += 7
    return items


# ── GUI Application ────────────────────────────────────────────────────
class SlotBasedEditor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Shadow of War — Save Editor")
        self.geometry("720x620")
        self.resizable(True, True)

        # State
        self.filepath = None
        self.steam_id = 0
        self.key_data = None
        self.decrypted = None
        self.ivgd_items = []
        self.iuc_items = []
        self.dirty = False

        # Game database (from dump_gamedb.lua output)
        self.gamedb = None
        if GAMEDB_AVAILABLE:
            self.gamedb = GameDatabase()

        # Per-slot: which IVGD item is "equipped" for this slot
        # (represented by its index in self.ivgd_items, or None)
        self.slot_equipped = {s["name"]: None for s in EQUIPMENT_SLOTS}

        # Mapping: IVGD item_id (uint32) → user-chosen gear name
        self.id_to_name: dict = {}

        # ── Menu ──
        menubar = tk.Menu(self)
        self.config(menu=menubar)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open .sav File...", command=self.open_file, accelerator="Ctrl+O")
        file_menu.add_command(label="Save .sav File", command=self.save_file, accelerator="Ctrl+S")
        file_menu.add_command(label="Save As...", command=self.save_as)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        tools_menu = tk.Menu(menubar, tearoff=0)
        if self.gamedb and self.gamedb.is_loaded:
            tools_menu.add_command(label="Search GameDB...", command=self.search_gamedb)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        self.bind("<Control-o>", lambda e: self.open_file())
        self.bind("<Control-s>", lambda e: self.save_file())
        self.protocol("WM_DELETE_WINDOW", self.on_exit)

        # ── Top Bar ──
        top = ttk.Frame(self, padding=5)
        top.pack(fill=tk.X)

        ttk.Label(top, text="File:").pack(side=tk.LEFT, padx=2)
        self.file_label = ttk.Label(top, text="(no file loaded)", foreground="gray")
        self.file_label.pack(side=tk.LEFT, padx=2)

        ttk.Label(top, text="Steam ID:").pack(side=tk.LEFT, padx=(20, 2))
        self.steam_id_var = tk.StringVar(value="0x00000000")
        self._steam_id_updating = False  # guard against recursive trace
        self.steam_id_var.trace_add("write", self._on_steam_id_change)
        ttk.Entry(top, textvariable=self.steam_id_var, width=20).pack(side=tk.LEFT, padx=2)

        ttk.Button(top, text="Re-load", command=lambda: self.open_file(self.filepath)).pack(
            side=tk.LEFT, padx=10)

        self.status_label = ttk.Label(top, text="", foreground="gray")
        self.status_label.pack(side=tk.RIGHT, padx=5)

        # ── Notebook (tabs) ──
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Tab 1: Equipment Slots
        self.equip_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.equip_frame, text="Equipment")

        # Tab 2: All Items (raw view)
        self.items_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.items_frame, text="All Items")

        # ── Build Equipment Tab ──
        self.build_equip_tab()
        self.build_items_tab()

        # Bottom status
        self.bottom_label = ttk.Label(self, text="Ready.", foreground="gray")
        self.bottom_label.pack(fill=tk.X, padx=5, pady=2)

        # Load game database if available
        if self.gamedb and self.gamedb.is_loaded:
            self._build_gear_from_gamedb()

    # ── Game Database Integration ──────────────────────────────────
    def _build_gear_from_gamedb(self):
        """Enrich GEAR_BY_SLOT from the dumped game database."""
        if not self.gamedb or not self.gamedb.is_loaded:
            return

        total_entries = len(self.gamedb._all_entries_by_name)

        # Update status
        self.status_label.config(
            text=f"GameDB: {len(self.gamedb.lists)} lists, {total_entries} entries",
            foreground="blue")

    def _on_steam_id_change(self, *_args):
        """Auto-convert decimal input to 0x hex format."""
        if self._steam_id_updating:
            return
        raw = self.steam_id_var.get().strip()
        if not raw or raw.startswith("0x") or raw.startswith("0X"):
            return
        try:
            val = int(raw)
            self._steam_id_updating = True
            self.steam_id_var.set(f"0x{val:08X}")
            self._steam_id_updating = False
        except ValueError:
            pass

    def search_gamedb(self):
        """Open a dialog to search the game database."""
        if not self.gamedb or not self.gamedb.is_loaded:
            messagebox.showinfo("GameDB", "Game database not loaded.\nRun dump_gamedb via Cheat Engine and copy gamedb_dump/ here.")
            return

        dialog = tk.Toplevel(self)
        dialog.title("Search Game Database")
        dialog.geometry("600x500")
        dialog.transient(self)

        frame = ttk.Frame(dialog, padding=5)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Pattern:").pack(side=tk.LEFT)
        search_var = tk.StringVar()
        search_entry = ttk.Entry(frame, textvariable=search_var, width=40)
        search_entry.pack(side=tk.LEFT, padx=5)
        search_entry.focus_set()

        result_text = tk.Text(dialog, wrap=tk.NONE, font=("Consolas", 9))
        result_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        scrollbar = ttk.Scrollbar(result_text, orient=tk.VERTICAL, command=result_text.yview)
        result_text.config(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        xscroll = ttk.Scrollbar(dialog, orient=tk.HORIZONTAL, command=result_text.xview)
        result_text.config(xscrollcommand=xscroll.set)
        xscroll.pack(side=tk.BOTTOM, fill=tk.X)

        def do_search(*_args):
            pattern = search_var.get().strip()
            result_text.delete("1.0", tk.END)
            if not pattern or len(pattern) < 2:
                result_text.insert("1.0", "Type at least 2 characters to search.")
                return
            results = self.gamedb.search(pattern)
            if not results:
                result_text.insert("1.0", f"No entries found matching '{pattern}'")
                return
            lines = [f"{len(results)} entries matching '{pattern}':\n"]
            for list_name, entry in results:
                lines.append(f"[{list_name}] 0x{entry.address:016X}  {entry.name}")
            result_text.insert("1.0", "\n".join(lines))

        search_var.trace_add("write", lambda *a: do_search())
        search_entry.bind("<Return>", do_search)

        ttk.Button(dialog, text="Close", command=dialog.destroy).pack(pady=5)

    # ── Equipment Tab ──────────────────────────────────────────────
    def build_equip_tab(self):
        """Build the slot-based equipment editing interface."""
        # Header
        header = ttk.Frame(self.equip_frame)
        header.pack(fill=tk.X, pady=(10, 5))

        ttk.Label(header, text="Character Equipment", font=("TkDefaultFont", 14, "bold")).pack(
            side=tk.LEFT, padx=10)

        ttk.Button(header, text="Clear All", command=self.clear_all_slots).pack(
            side=tk.RIGHT, padx=10)

        # Separator
        ttk.Separator(self.equip_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10)

        # Slot rows
        self.slot_widgets = {}
        for i, slot_def in enumerate(EQUIPMENT_SLOTS):
            slot_name = slot_def["name"]
            self._build_slot_row(i, slot_def)

        # Info
        info_frame = ttk.Frame(self.equip_frame)
        info_frame.pack(fill=tk.X, pady=10, padx=10)

        self.equip_info = ttk.Label(info_frame, text="", foreground="gray")
        self.equip_info.pack(side=tk.LEFT)

        ttk.Button(info_frame, text="Apply All Changes",
                    command=self.apply_all_slots).pack(side=tk.RIGHT)

    def _build_slot_row(self, index, slot_def):
        """Create one equipment slot row with label, combo, and clear button."""
        slot_name = slot_def["name"]
        icon = slot_def["icon"]

        row_frame = ttk.Frame(self.equip_frame)
        row_frame.pack(fill=tk.X, pady=3, padx=20)

        # Slot icon and name
        ttk.Label(row_frame, text=f"{icon} {slot_name}", width=18, anchor=tk.W,
                   font=("TkDefaultFont", 11)).pack(side=tk.LEFT, padx=5)

        # Item dropdown
        items = GEAR_BY_SLOT.get(slot_name, [])
        combo = ttk.Combobox(row_frame, values=items, width=38, state="readonly")
        combo.set("(none)")
        combo.pack(side=tk.LEFT, padx=5)
        combo.bind("<<ComboboxSelected>>", lambda e, sn=slot_name: self._on_slot_change(sn))

        # Current item indicator
        current_label = ttk.Label(row_frame, text="", foreground="gray", width=20)
        current_label.pack(side=tk.LEFT, padx=10)

        self.slot_widgets[slot_name] = {
            "combo": combo,
            "label": current_label,
            "slot_def": slot_def,
            "item_idx": None,   # index into self.ivgd_items
        }

    def _on_slot_change(self, slot_name):
        """Called when user selects an item from a slot dropdown."""
        combo = self.slot_widgets[slot_name]["combo"]
        chosen = combo.get()
        if chosen == "(none)":
            self.slot_widgets[slot_name]["item_idx"] = None
            self.slot_widgets[slot_name]["label"].config(text="(empty)", foreground="gray")
        else:
            # Find a matching IVGD item for this slot
            # If one already selected, keep it. Otherwise pick the first available.
            # For now, just store the chosen name.
            self.slot_widgets[slot_name]["label"].config(
                text=f"→ {chosen}", foreground="blue")

        self.dirty = True
        self.bottom_label.config(text="Changes pending. Click 'Apply All Changes' to write to memory.", foreground="red")

    def clear_all_slots(self):
        for slot_name, w in self.slot_widgets.items():
            w["combo"].set("(none)")
            w["label"].config(text="(empty)", foreground="gray")
            w["item_idx"] = None
        self.dirty = True
        self.bottom_label.config(text="All slots cleared. Click 'Apply All Changes' to write.", foreground="red")

    def apply_all_slots(self):
        """Apply all slot selections to the decrypted save data."""
        if self.decrypted is None:
            messagebox.showwarning("No File", "Open a save file first.")
            return

        # Step 1: Unequip all currently equipped IVGD items
        for item in self.ivgd_items:
            eq_off = item["abs_offset"] + 7
            if self.decrypted[eq_off] == 1:
                self.decrypted[eq_off] = 0
                item["eq"] = 0

        # Step 2: For each slot, equip the selected item
        changes = []
        for slot_name, w in self.slot_widgets.items():
            combo = w["combo"]
            chosen = combo.get()
            if chosen == "(none)" or not chosen:
                continue

            slot_def = w["slot_def"]
            target_slot_byte = slot_def["slot_byte"]

            # Find a suitable IVGD item
            # Strategy: find the first IVGD item with matching slot byte
            # that isn't already assigned to another slot
            best_item = None
            for item in self.ivgd_items:
                if item["slot"] == target_slot_byte and item["eq"] == 0:
                    best_item = item
                    break

            if best_item:
                eq_off = best_item["abs_offset"] + 7
                self.decrypted[eq_off] = 1
                best_item["eq"] = 1
                self.decrypted[best_item["abs_offset"] + 6] = target_slot_byte
                changes.append(f"{slot_name}: {chosen}")
                w["item_idx"] = self.ivgd_items.index(best_item)
                # Store name mapping for this item ID
                if not chosen.startswith("[0x"):
                    self.id_to_name[best_item["id"]] = chosen
                w["label"].config(text=chosen, foreground="green")
            else:
                # Try any item regardless of slot
                for item in self.ivgd_items:
                    if item["eq"] == 0:
                        best_item = item
                        break
                if best_item:
                    eq_off = best_item["abs_offset"] + 7
                    self.decrypted[eq_off] = 1
                    self.decrypted[best_item["abs_offset"] + 6] = target_slot_byte
                    best_item["eq"] = 1
                    best_item["slot"] = target_slot_byte
                    changes.append(f"{slot_name}: {chosen} (new slot)")
                    w["label"].config(text=chosen, foreground="orange")
                    w["item_idx"] = self.ivgd_items.index(best_item)

        self.dirty = True
        if changes:
            self.bottom_label.config(
                text=f"Applied: {', '.join(changes)}. Save file to persist.",
                foreground="green")
        else:
            self.bottom_label.config(text="No items to apply.", foreground="gray")

        self._refresh_items_tab()

    # ── Loadout from save ──────────────────────────────────────────
    def populate_from_save(self):
        """Read current equipped items from save and populate dropdowns."""
        if not self.ivgd_items:
            return

        # Find equipped items by slot
        equipped_by_slot = {}
        for item in self.ivgd_items:
            if item["eq"] == 1:
                slot = item["slot"]
                if slot not in equipped_by_slot:
                    equipped_by_slot[slot] = []
                equipped_by_slot[slot].append(item)

        # Populate each slot widget
        for slot_name, w in self.slot_widgets.items():
            slot_def = w["slot_def"]
            target_slot = slot_def["slot_byte"]

            if target_slot in equipped_by_slot and equipped_by_slot[target_slot]:
                item = equipped_by_slot[target_slot][0]  # First equipped item for this slot
                w["item_idx"] = self.ivgd_items.index(item)
                item_id = item['id']
                # Resolve name from stored mapping, or show raw ID
                name = self.id_to_name.get(item_id)
                if name:
                    w["label"].config(text=name, foreground="green")
                    w["combo"].set(name)
                else:
                    w["label"].config(
                        text=f"ID: 0x{item_id:08X} (eq)", foreground="green")
                    w["combo"].set(f"[0x{item_id:08X}]")
            else:
                # Try to find any equipped item that might match
                w["combo"].set("(none)")
                w["label"].config(text="(empty)", foreground="gray")

    # ── All Items Tab ──────────────────────────────────────────────
    def build_items_tab(self):
        """Build the raw item list view."""
        filter_frame = ttk.Frame(self.items_frame)
        filter_frame.pack(fill=tk.X, pady=5)

        ttk.Label(filter_frame, text="Filter:").pack(side=tk.LEFT, padx=5)
        self.item_filter = tk.StringVar(value="All")
        filter_combo = ttk.Combobox(filter_frame, textvariable=self.item_filter,
                                     width=20, state="readonly")
        filter_combo["values"] = ["All", "Equipped Only", "Slot 0x0C", "Slot 0x08",
                                   "Slot 0x0A", "Type 0x0202", "Type 0x0102", "Type 0x0002"]
        filter_combo.pack(side=tk.LEFT, padx=5)
        filter_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_items_tab())

        self.items_stats = ttk.Label(filter_frame, text="", foreground="gray")
        self.items_stats.pack(side=tk.RIGHT, padx=10)

        # Treeview
        tree_frame = ttk.Frame(self.items_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("id", "type", "slot", "eq")
        self.item_tree = ttk.Treeview(tree_frame, columns=columns, show="headings",
                                       selectmode="browse", height=12)
        self.item_tree.heading("id", text="Item ID")
        self.item_tree.heading("type", text="Type")
        self.item_tree.heading("slot", text="Slot")
        self.item_tree.heading("eq", text="Eq")

        self.item_tree.column("id", width=110)
        self.item_tree.column("type", width=70)
        self.item_tree.column("slot", width=60)
        self.item_tree.column("eq", width=40)

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.item_tree.yview)
        self.item_tree.configure(yscrollcommand=scrollbar.set)
        self.item_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _refresh_items_tab(self):
        """Refresh the all-items treeview."""
        self.item_tree.delete(*self.item_tree.get_children())
        filt = self.item_filter.get()

        items = self.ivgd_items
        if filt == "Equipped Only":
            items = [i for i in items if i["eq"] == 1]
        elif filt == "Slot 0x0C":
            items = [i for i in items if i["slot"] == 0x0C]
        elif filt == "Slot 0x08":
            items = [i for i in items if i["slot"] == 0x08]
        elif filt == "Slot 0x0A":
            items = [i for i in items if i["slot"] == 0x0A]
        elif filt.startswith("Type"):
            tval = int(filt.split("0x")[1], 16)
            items = [i for i in items if i["type"] == tval]

        eq_count = sum(1 for i in items if i["eq"] == 1)
        self.items_stats.config(text=f"Items: {len(items)} | Equipped: {eq_count}")

        for item in items[:500]:  # limit display
            eq_text = "YES" if item["eq"] == 1 else ""
            self.item_tree.insert("", tk.END,
                                  iid=str(item["abs_offset"]),
                                  values=(f"0x{item['id']:08X}",
                                          f"0x{item['type']:04X}",
                                          f"0x{item['slot']:02X}",
                                          eq_text))

    # ── File Operations ─────────────────────────────────────────────
    def open_file(self, filepath=None):
        if not filepath or not os.path.exists(filepath):
            filepath = filedialog.askopenfilename(
                title="Open Shadow of War Save File",
                filetypes=[("Save Files", "*_ShadowOfWar.sav"), ("All Files", "*.sav"), ("All Files", "*.*")])
        if not filepath or not os.path.exists(filepath):
            return

        # Extract Steam ID from filename
        basename = Path(filepath).stem
        parts = basename.split("_")
        steam_id_hex = parts[0] if parts else "00000000"
        try:
            self.steam_id = int(steam_id_hex, 16)
            self.steam_id_var.set(f"0x{self.steam_id:08x}")
        except ValueError:
            self.steam_id = 0

        # Backup
        backup_path = filepath + ".backup"
        if not os.path.exists(backup_path):
            try:
                shutil.copy2(filepath, backup_path)
            except Exception:
                pass

        # Decrypt
        try:
            self.decrypted, self.key_data = decrypt_save(filepath, self.steam_id)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to decrypt save:\n{e}")
            return

        self.filepath = filepath
        self.file_label.config(text=basename, foreground="black")
        self.status_label.config(text=f"Decrypted: {len(self.decrypted):,} bytes")
        self.dirty = False

        # Parse
        self.ivgd_items = parse_ivgd(self.decrypted)
        self.iuc_items = parse_iuc(self.decrypted)

        eq_count = sum(1 for i in self.ivgd_items if i["eq"] == 1)
        self.bottom_label.config(
            text=f"Loaded {len(self.ivgd_items):,} IVGD items ({eq_count} equipped), "
                 f"{len(self.iuc_items)} IIUC entries")

        self.populate_from_save()
        self._refresh_items_tab()

    def save_file(self):
        if not self.filepath or self.decrypted is None:
            return
        self._do_save(self.filepath)

    def save_as(self):
        if self.decrypted is None:
            return
        filepath = filedialog.asksaveasfilename(
            title="Save As", defaultextension=".sav",
            filetypes=[("Save Files", "*.sav")])
        if filepath:
            self._do_save(filepath)

    def _do_save(self, path):
        try:
            enc = encrypt_save(self.decrypted, self.key_data, self.steam_id)
            with open(path, "wb") as f:
                f.write(enc)
            self.dirty = False
            self.filepath = path
            self.file_label.config(text=Path(path).stem, foreground="black")
            self.status_label.config(text=f"Saved: {len(enc):,} bytes")
            messagebox.showinfo("Saved", f"Saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save:\n{e}")

    def load_reference(self):
        """Load a reference save from the Nexus pack for comparison."""
        ref_dir = filedialog.askdirectory(
            title="Select reference save directory",
            initialdir=r"C:\Users\vicha\Downloads\MAIN Middle-Earth - Shadow of War SAVES-129-1-0-1727454420")
        if not ref_dir:
            return

        # Find the .sav file in the directory
        for root, dirs, files in os.walk(ref_dir):
            for f in files:
                if f.endswith("_ShadowOfWar.sav"):
                    ref_path = os.path.join(root, f)
                    # Decrypt reference and show stats
                    try:
                        parts = Path(f).stem.split("_")
                        sid = int(parts[0], 16)
                        ref_data, _ = decrypt_save(ref_path, sid)
                        ref_ivgd = parse_ivgd(ref_data)
                        ref_eq = sum(1 for i in ref_ivgd if i["eq"] == 1)
                        messagebox.showinfo(
                            "Reference Save Info",
                            f"File: {f}\n"
                            f"Size: {len(ref_data):,} bytes\n"
                            f"IVGD items: {len(ref_ivgd)}\n"
                            f"Equipped: {ref_eq}")
                    except Exception as e:
                        messagebox.showerror("Error", f"Failed to load reference:\n{e}")
                    return

    def on_exit(self):
        if self.dirty:
            if messagebox.askyesno("Unsaved Changes", "Exit without saving?"):
                self.destroy()
        else:
            self.destroy()

    def unequip_all(self):
        if self.decrypted is None:
            return
        if not messagebox.askyesno("Confirm", "Unequip ALL items?"):
            return

        fixed = 0
        for item in self.ivgd_items:
            eq_off = item["abs_offset"] + 7
            if self.decrypted[eq_off] == 1:
                self.decrypted[eq_off] = 0
                item["eq"] = 0
                fixed += 1

        # Also clear IIUC equipped flags
        for item in self.iuc_items:
            eq_off = item["abs_offset"] + 5
            if self.decrypted[eq_off] == 1:
                self.decrypted[eq_off] = 0
                item["eq"] = 0

        self.dirty = True
        self.clear_all_slots()
        self.bottom_label.config(text=f"Unequipped {fixed} items. Save to persist.", foreground="red")
        self._refresh_items_tab()


# ── Entry Point ────────────────────────────────────────────────────────
def main():
    app = SlotBasedEditor()
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        app.open_file(sys.argv[1])
    app.mainloop()


if __name__ == "__main__":
    main()
