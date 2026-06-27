#!/usr/bin/env python3
"""
gamedb.py — Shadow of War Game Database Loader
================================================
Loads dumped game database text files (from dump_gamedb.lua) and provides
name-resolution helpers for the save editor.

Usage (CLI):
    python gamedb.py                        # Show all loaded lists + entry counts
    python gamedb.py --list Inventory/Items # Show all entries in a list
    python gamedb.py --find Urfael          # Search all entries by name

Usage (import):
    from gamedb import GameDatabase
    db = GameDatabase("gamedb_dump/")
    items = db.get_list("Inventory/Items")
    for entry in items:
        print(entry.name)

The dump files are expected in: gamedb_dump/*.txt
Each file format:
    # Shadow of War Game Database Dump
    # List: Inventory/Items
    # Entry count: XXX
    # Entry stride: 0x28
    # Format: address|name|hex_bytes
    <blank line>
    0000000000000000|<None>|<hex bytes>
    0000000000000028|Item_Gear_Sword_Urfael|<hex bytes>
    ...
"""

import os
import re
import sys
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple, Iterator


class GameListEntry:
    """A single entry in a game database list."""
    __slots__ = ("index", "address", "name", "hex_bytes", "list_name")

    def __init__(self, index: int, address: int, name: str,
                 hex_bytes: str = "", list_name: str = ""):
        self.index = index
        self.address = address
        self.name = name
        self.hex_bytes = hex_bytes
        self.list_name = list_name

    def __repr__(self):
        return f"GameListEntry({self.name!r}, addr=0x{self.address:016X})"

    def __str__(self):
        return self.name

    @property
    def is_null(self) -> bool:
        return self.name == "<None>" or self.name == ""


class GameList:
    """A named list of entries from the game database."""
    __slots__ = ("name", "entries", "entry_stride", "_by_name", "_by_address")

    def __init__(self, name: str, entries: List[GameListEntry],
                 entry_stride: int = 0x28):
        self.name = name
        self.entries = entries
        self.entry_stride = entry_stride
        self._by_name: Dict[str, GameListEntry] = {}
        self._by_address: Dict[int, GameListEntry] = {}
        for e in entries:
            if e.name:
                self._by_name[e.name] = e
            self._by_address[e.address] = e

    def __len__(self):
        return len(self.entries)

    def __iter__(self) -> Iterator[GameListEntry]:
        return iter(self.entries)

    def __getitem__(self, idx) -> GameListEntry:
        return self.entries[idx]

    def __repr__(self):
        return f"GameList({self.name!r}, {len(self.entries)} entries)"

    def get_by_name(self, name: str) -> Optional[GameListEntry]:
        return self._by_name.get(name)

    def get_by_address(self, addr: int) -> Optional[GameListEntry]:
        return self._by_address.get(addr)

    def find(self, pattern: str, case_sensitive: bool = False) -> List[GameListEntry]:
        """Find entries whose name contains `pattern`."""
        if case_sensitive:
            return [e for e in self.entries if pattern in e.name]
        pl = pattern.lower()
        return [e for e in self.entries if pl in e.name.lower()]

    @property
    def non_null_entries(self) -> List[GameListEntry]:
        return [e for e in self.entries if not e.is_null]


# ── Known list names from SeiKur0's CT ───────────────────────────────────
KNOWN_LISTS = [
    "Inventory/Items",
    "Inventory/EquippedWeaponData",
    "Inventory/ArmorData",
    "Inventory/Affix/Definition",
    "Faction/Loot/NemesisGear",
    "Faction/Traits/Marker",
    "Faction/Traits/Picker",
    "Faction/AppearanceTags/Tags",
    "Combat/Tree",
    "Faction/Traits/PickerLevelRemap",
    "Faction/Tribes/Definitions",
    "Faction/Roles/Definitions",
    "Character/Models",
    "Faction/Personalities",
    "Model",
    "Model/SimpleModelPieces",
    "Model/SimpleModelHeads",
]

# ── Item category classification patterns ────────────────────────────────
ITEM_PATTERNS = {
    "Sword":    re.compile(r"Sword|Urfael", re.IGNORECASE),
    "Dagger":   re.compile(r"Dagger|Acharn", re.IGNORECASE),
    "Bow":      re.compile(r"Bow|Hammer|Azkar", re.IGNORECASE),
    "Armor":    re.compile(r"Armor|Ranger", re.IGNORECASE),
    "Cloak":    re.compile(r"Cloak", re.IGNORECASE),
    "Ring":     re.compile(r"Rune|R.?ing", re.IGNORECASE),
}


class GameDatabase:
    """Loads and indexes all dumped game database lists."""

    def __init__(self, dump_dir: str = "gamedb_dump"):
        self.dump_dir = dump_dir
        self.lists: Dict[str, GameList] = OrderedDict()
        self._all_entries_by_name: Dict[str, GameListEntry] = {}
        self._all_entries_by_address: Dict[int, GameListEntry] = {}
        self._loaded = False
        self._try_load()

    # ── Loading ──────────────────────────────────────────────────────

    def _try_load(self):
        """Try to load dump files. Silently skip if directory doesn't exist."""
        if not os.path.isdir(self.dump_dir):
            return
        for filename in sorted(os.listdir(self.dump_dir)):
            if not filename.endswith(".txt"):
                continue
            filepath = os.path.join(self.dump_dir, filename)
            self._load_file(filepath)
        self._build_indexes()
        self._loaded = True

    def _load_file(self, filepath: str):
        """Parse a single dump file into a GameList."""
        list_name = None
        entry_stride = 0x28
        entries: List[GameListEntry] = []

        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n\r")
                if line.startswith("# List: "):
                    list_name = line[len("# List: "):].strip()
                elif line.startswith("# Entry stride: "):
                    try:
                        entry_stride = int(line.split("0x")[1], 16)
                    except (IndexError, ValueError):
                        pass
                elif line.startswith("#") or line.strip() == "":
                    continue
                elif "|" in line and list_name:
                    parts = line.split("|", 2)
                    try:
                        addr = int(parts[0], 16)
                    except ValueError:
                        continue
                    name = parts[1] if len(parts) > 1 else ""
                    hexb = parts[2] if len(parts) > 2 else ""
                    entries.append(GameListEntry(
                        index=len(entries),
                        address=addr,
                        name=name,
                        hex_bytes=hexb,
                        list_name=list_name,
                    ))

        if list_name and entries:
            self.lists[list_name] = GameList(list_name, entries, entry_stride)

    def _build_indexes(self):
        """Build global name/address lookup dictionaries."""
        for glist in self.lists.values():
            for entry in glist.entries:
                if entry.name and entry.name != "<None>":
                    self._all_entries_by_name[entry.name] = entry
                self._all_entries_by_address[entry.address] = entry

    # ── Accessors ────────────────────────────────────────────────────

    @property
    def is_loaded(self) -> bool:
        return self._loaded and len(self.lists) > 0

    def get_list(self, name: str) -> Optional[GameList]:
        return self.lists.get(name)

    def resolve_name(self, address: int) -> Optional[str]:
        """Given an address (from dropdown value), return the entry name."""
        entry = self._all_entries_by_address.get(address)
        return entry.name if entry else None

    def find_by_name(self, name: str) -> Optional[GameListEntry]:
        """Search all lists for an entry by exact name."""
        return self._all_entries_by_name.get(name)

    def search(self, pattern: str, case_sensitive: bool = False) -> List[Tuple[str, GameListEntry]]:
        """Search all lists for entries matching `pattern` in name."""
        results = []
        pl = pattern if case_sensitive else pattern.lower()
        for list_name, glist in self.lists.items():
            for entry in glist.entries:
                ename = entry.name if case_sensitive else entry.name.lower()
                if pl in ename:
                    results.append((list_name, entry))
        return results

    # ── Categorized access ───────────────────────────────────────────

    def get_all_entries(self) -> List[GameListEntry]:
        """Return all non-null entries across all lists."""
        results = []
        for glist in self.lists.values():
            results.extend(glist.non_null_entries)
        return results

    def get_all_entry_names(self) -> List[str]:
        """Return all unique non-null entry names across all lists."""
        return sorted(self._all_entries_by_name.keys())

    def get_entries_matching(self, *patterns: str, case_sensitive: bool = False) -> List[GameListEntry]:
        """Return entries whose names match any of the given regex patterns."""
        pats = [re.compile(p, 0 if case_sensitive else re.IGNORECASE) for p in patterns]
        results = []
        seen = set()
        for entry in self.get_all_entries():
            if entry.name in seen:
                continue
            for pat in pats:
                if pat.search(entry.name):
                    seen.add(entry.name)
                    results.append(entry)
                    break
        return results

    def get_affixes(self) -> List[GameListEntry]:
        """Return all item effect/affix definitions."""
        gl = self.get_list("Inventory/Affix/Definition")
        return gl.non_null_entries if gl else []

    def get_weapon_data(self) -> List[GameListEntry]:
        gl = self.get_list("Inventory/EquippedWeaponData")
        return gl.non_null_entries if gl else []

    def get_armor_data(self) -> List[GameListEntry]:
        gl = self.get_list("Inventory/ArmorData")
        return gl.non_null_entries if gl else []

    def get_traits_marker(self) -> List[GameListEntry]:
        """Orc marker traits (48 entries)."""
        gl = self.get_list("Faction/Traits/Marker")
        return gl.non_null_entries if gl else []

    def get_traits_picker(self) -> List[GameListEntry]:
        """Orc picker abilities (56 entries)."""
        gl = self.get_list("Faction/Traits/Picker")
        return gl.non_null_entries if gl else []

    def get_tribes(self) -> List[GameListEntry]:
        gl = self.get_list("Faction/Tribes/Definitions")
        return gl.non_null_entries if gl else []

    def get_roles(self) -> List[GameListEntry]:
        gl = self.get_list("Faction/Roles/Definitions")
        return gl.non_null_entries if gl else []

    def get_classes(self) -> List[GameListEntry]:
        gl = self.get_list("Combat/Tree")
        return gl.non_null_entries if gl else []

    def get_personalities(self) -> List[GameListEntry]:
        gl = self.get_list("Faction/Personalities")
        return gl.non_null_entries if gl else []

    def get_models(self) -> List[GameListEntry]:
        gl = self.get_list("Character/Models")
        return gl.non_null_entries if gl else []

    def get_nemesis_gear(self) -> List[GameListEntry]:
        """Legendary gear loot table entries."""
        gl = self.get_list("Faction/Loot/NemesisGear")
        return gl.non_null_entries if gl else []

    def classify_gear_by_slot(self) -> Dict[str, List[GameListEntry]]:
        """Search all lists for entries matching gear slot patterns."""
        categorized: Dict[str, List[GameListEntry]] = {
            "Sword": [], "Dagger": [], "Bow": [],
            "Armor": [], "Cloak": [], "Ring": [],
            "Other": [],
        }
        for entry in self.get_all_entries():
            matched = False
            for slot, pattern in ITEM_PATTERNS.items():
                if pattern.search(entry.name):
                    categorized[slot].append(entry)
                    matched = True
                    break
            if not matched:
                categorized["Other"].append(entry)
        return categorized

    # ── Info / Reporting ─────────────────────────────────────────────

    def summary(self) -> str:
        """Return a multi-line summary of loaded database contents."""
        lines = []
        lines.append(f"GameDatabase: {self.dump_dir}")
        lines.append(f"  Lists loaded: {len(self.lists)}")
        lines.append(f"  Total entries: {len(self._all_entries_by_name)} (non-null)")
        lines.append("")
        for name, glist in self.lists.items():
            non_null = len(glist.non_null_entries)
            lines.append(f"  {name}: {len(glist)} entries ({non_null} non-null)")
        return "\n".join(lines)


# ── CLI ────────────────────────────────────────────────────────────────
def main():
    db = GameDatabase()

    if not db.is_loaded:
        print("No game database dump found.")
        print(f"Expected directory: {db.dump_dir}")
        print("Run dump_gamedb.lua in Cheat Engine first to generate dump files.")
        sys.exit(1)

    if "--list" in sys.argv:
        idx = sys.argv.index("--list")
        if idx + 1 < len(sys.argv):
            name = sys.argv[idx + 1]
            gl = db.get_list(name)
            if gl:
                print(f"=== {name} ({len(gl)} entries) ===")
                for e in gl.entries:
                    print(f"  [{e.index:4d}] 0x{e.address:016X}  {e.name}")
                return
            else:
                print(f"List '{name}' not found.")
                print("Available lists:")
                for n in db.lists:
                    print(f"  {n}")
                sys.exit(1)

    if "--find" in sys.argv:
        idx = sys.argv.index("--find")
        if idx + 1 < len(sys.argv):
            pattern = sys.argv[idx + 1]
            results = db.search(pattern)
            if results:
                print(f"=== Search results for '{pattern}' ({len(results)} hits) ===")
                for list_name, entry in results:
                    print(f"  [{list_name}] 0x{entry.address:016X}  {entry.name}")
            else:
                print(f"No entries found matching '{pattern}'")
            return

    # Default: show summary
    print(db.summary())


if __name__ == "__main__":
    main()
