#!/usr/bin/env python3
"""
Stormgate Replay Parser
Parses .SGReplay files and extracts game data, player actions, chat, etc.

Usage: python parse_sgreplay.py <replay_file.SGReplay>
"""

import struct
import json
import zlib
import sys
import os
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Import from modular components
from protobuf import (
    gzip_header_len,
    decode_varint,
    decode_message,
    get_nested,
    find_all_strings,
    simplify_protobuf,
    u64_to_i64,
    fixed_to_world,
    pb_get,
    pb_has,
)
from entity_tracker import EntityTracker
from replay_analyzers import (
    frame_to_time,
    frame_to_seconds,
    FRAME_RATE_HZ,
    UPGRADE_FRIENDLY_NAMES,
    UPGRADE_KEYWORDS,
    STORMGATE_REWARD_NAMES,
)

# Try to import ability lookup for name resolution
try:
    from ability_lookup import AbilityLookup
    ABILITY_LOOKUP_AVAILABLE = True
except ImportError:
    ABILITY_LOOKUP_AVAILABLE = False
    AbilityLookup = None

# Load building lookup from buildings.json if available
BUILDINGS_JSON_PATH = os.path.join(os.path.dirname(__file__), 'buildings.json')
BUILDING_LOOKUP = {}
try:
    if os.path.exists(BUILDINGS_JSON_PATH):
        with open(BUILDINGS_JSON_PATH, 'r') as f:
            BUILDING_LOOKUP = {int(k): v for k, v in json.load(f).items()}
except Exception:
    pass

# Compatibility aliases for internal use
_gzip_header_len = gzip_header_len
_u64_to_i64 = u64_to_i64
_fixed_to_world = fixed_to_world


class _LegacyFunctionsRemoved:
    """
    The following functions have been moved to separate modules:
    - protobuf.py: gzip_header_len, decode_varint, decode_message, get_nested,
                   find_all_strings, simplify_protobuf, u64_to_i64, fixed_to_world
    - entity_tracker.py: EntityTracker class
    - replay_analyzers.py: frame_to_time, frame_to_seconds, analysis constants
    """
    pass


class SGReplayParser:
    def __init__(
        self,
        filepath: str,
        ability_lookup: Optional['AbilityLookup'] = None,
        *,
        include_bytes: bool = False,
        bytes_hex_limit: int = 64,
    ):
        self.filepath = filepath
        self.header = {}
        self.messages = []
        self.raw_messages = []  # list of {'length': int, 'raw': bytes} for debugging/completeness checks
        self.players = {}
        self.actions = []
        self.chat = []
        self.positions = []
        self.map_name = None
        self.ability_lookup = ability_lookup
        self.include_bytes = include_bytes
        self.bytes_hex_limit = bytes_hex_limit
        self.entity_tracker = EntityTracker(ability_lookup)
        self.target_type_stats = Counter()  # track all target_type usage
        self.ability_id_stats = Counter()   # track all ability_id usage
        self.max_sync_time = 0  # max sync_1 value (game time in ticks, excludes loading)
        # Decompression/format details (helps confirm completeness)
        self.raw_data = b""
        self.gzip_header_len = 0
        self.gzip_trailer = None  # {'crc32': int, 'isize': int} when available
        self.compressed_unused = b""  # bytes after deflate stream in the compressed payload
        self.compressed_unused_len = 0
        # Some replays include an uncompressed protobuf footer after the gzip trailer.
        self.footer_protobuf = None  # decoded protobuf dict (typed)
        self.footer = None  # simplified footer protobuf (JSON-friendly)

    def load(self):
        """Load and decompress the replay file"""
        with open(self.filepath, 'rb') as f:
            header_data = f.read(20)
            self.header = {
                'magic': struct.unpack('<I', header_data[0:4])[0],
                'version': struct.unpack('<I', header_data[4:8])[0],
                'data_offset': struct.unpack('<I', header_data[8:12])[0],
                'changelist': struct.unpack('<I', header_data[12:16])[0],
                'flags': struct.unpack('<I', header_data[16:20])[0],
            }
            payload = f.read()

        # Decompress Stormgate payload: gzip header + raw deflate stream (+ trailer/extra bytes).
        offset = 0
        if payload.startswith(b'\x1f\x8b'):
            try:
                offset = _gzip_header_len(payload)
            except Exception:
                # Fallback to the common 10-byte header if parsing fails
                offset = 10
        self.gzip_header_len = offset

        decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
        self.raw_data = decompressor.decompress(payload[offset:]) + decompressor.flush()

        # Bytes after deflate stream in the compressed payload (often gzip trailer + extra data).
        # IMPORTANT: These bytes are NOT part of the decompressed message stream and were
        # previously ignored, which can drop useful metadata.
        self.compressed_unused = decompressor.unused_data or b""
        self.compressed_unused_len = len(self.compressed_unused)

        # Preserve backwards-compat attr (was used for debugging only)
        self._decompress_unused_bytes = self.compressed_unused_len

        # If this is a gzip-wrapped payload, the first 8 bytes after the deflate stream
        # are usually the gzip trailer: CRC32 + ISIZE (RFC 1952). Some replays then append
        # an *uncompressed* protobuf message containing metadata.
        extra_after_trailer = self.compressed_unused
        self.gzip_trailer = None
        if payload.startswith(b'\x1f\x8b') and len(extra_after_trailer) >= 8:
            try:
                crc32, isize = struct.unpack('<II', extra_after_trailer[:8])
                self.gzip_trailer = {'crc32': crc32, 'isize': isize}
                extra_after_trailer = extra_after_trailer[8:]
            except Exception:
                # If trailer parsing fails, just treat everything as extra.
                extra_after_trailer = self.compressed_unused

        # Try to decode any extra bytes as protobuf (either a stream of length-prefixed
        # messages or a single message). This makes exports more complete for reverse engineering.
        self.footer_protobuf = None
        self.footer = None
        if extra_after_trailer:
            decoded = None

            # Attempt: length-prefixed message stream (must consume ALL bytes to be accepted)
            try:
                pos = 0
                footer_msgs = []
                while pos < len(extra_after_trailer):
                    length, pos2 = decode_varint(extra_after_trailer, pos)
                    if length <= 0 or pos2 + length > len(extra_after_trailer):
                        footer_msgs = []
                        break
                    msg_data = extra_after_trailer[pos2:pos2+length]
                    m = decode_message(msg_data)
                    if not m:
                        footer_msgs = []
                        break
                    footer_msgs.append(m)
                    pos = pos2 + length
                if footer_msgs and pos == len(extra_after_trailer):
                    # Represent multiple footer messages under a synthetic dict key
                    decoded = {'_footer_stream': footer_msgs}
            except Exception:
                decoded = None

            # Fallback: single protobuf message
            if decoded is None:
                try:
                    decoded = decode_message(extra_after_trailer)
                except Exception:
                    decoded = None

            if decoded:
                self.footer_protobuf = decoded
                # If we wrapped a footer stream, simplify each message; otherwise simplify directly.
                if isinstance(decoded, dict) and '_footer_stream' in decoded:
                    self.footer = {
                        '_footer_stream': [
                            simplify_protobuf(
                                m,
                                include_bytes=self.include_bytes,
                                bytes_hex_limit=self.bytes_hex_limit,
                            )
                            for m in decoded['_footer_stream']
                        ]
                    }
                else:
                    self.footer = simplify_protobuf(
                        decoded,
                        include_bytes=self.include_bytes,
                        bytes_hex_limit=self.bytes_hex_limit,
                    )

        return self

    def parse(self):
        """Parse all messages from the replay"""
        pos = 0
        while pos < len(self.raw_data):
            length, pos = decode_varint(self.raw_data, pos)
            if length <= 0 or pos + length > len(self.raw_data):
                break
            msg_data = self.raw_data[pos:pos+length]
            pos += length
            self.raw_messages.append({'length': length, 'raw': msg_data})
            decoded = decode_message(msg_data)
            if decoded:
                self.messages.append(decoded)

        self._extract_game_info()
        self._extract_actions()
        self._extract_chat()
        self._track_entities()
        return self

    def _track_entities(self):
        """Build entity tracking and stats from actions."""
        for action in self.actions:
            # Track entities
            self.entity_tracker.record_action(action)

            # Track target_type stats
            target_type = action.get('target_type')
            if target_type and isinstance(target_type, (int, str)):
                name = action.get('target_type_name') or str(target_type)
                self.target_type_stats[name] += 1

            # Track ability_id stats
            ability_id = action.get('ability_id')
            if ability_id and isinstance(ability_id, (int, str)):
                name = action.get('ability_name') or str(ability_id)
                self.ability_id_stats[name] += 1

        # Infer entity owners
        self.entity_tracker.infer_owners(self.players)

    def _extract_game_info(self):
        """Extract map name and player info"""
        # First pass: get player info from field 45 (actual player_id -> name mapping)
        # Field 45 contains the TRUE mapping between player_id used in actions and player names
        for msg in self.messages[:50]:
            pid = get_nested(msg, 2)
            content = get_nested(msg, 3, 1)
            if not content:
                continue

            # Player info from field 45 (authoritative source for player_id -> name)
            # Structure: field 45 -> entry.v.5 -> dict with field 1 containing name
            field45 = pb_get(content, 45)
            if field45 and pid and isinstance(pid, int) and pid != 64:
                entries = field45 if isinstance(field45, list) else [field45]
                for entry in entries:
                    if isinstance(entry, dict) and entry.get('t') == 'm':
                        # entry['v'][5] is a dict like {1: [{'t': 's', 'v': 'PlayerName'}], ...}
                        name_data = get_nested(entry['v'], 5)
                        if name_data and isinstance(name_data, dict):
                            name = get_nested(name_data, 1)
                            if name and isinstance(name, str):
                                self.players[pid] = name

        # Second pass: map name and fallback to field 37 if field 45 didn't provide players
        for msg in self.messages[:50]:
            pid = get_nested(msg, 2)

            # Map name (try multiple paths)
            if not self.map_name:
                for path in [(3, 1, 3, 2), (3, 1, 1, 3, 2), (3, 1, 1, 2)]:
                    map_name = get_nested(msg, *path)
                    if map_name and isinstance(map_name, str) and len(map_name) > 3:
                        self.map_name = map_name
                        break

            content = get_nested(msg, 3, 1)
            if not content:
                continue

            # Fallback: Player info from field 37 (only if not already set from field 45)
            field37 = pb_get(content, 37)
            if field37:
                entries = field37 if isinstance(field37, list) else [field37]
                for entry in entries:
                    if isinstance(entry, dict) and entry.get('t') == 'm':
                        slot = get_nested(entry['v'], 2)
                        name = get_nested(entry['v'], 3)
                        if slot and isinstance(slot, int) and name and isinstance(name, str):
                            if slot not in self.players:
                                self.players[slot] = name

        # Fallback: try to get missing player names from footer
        # Footer field 3 contains player results with slot and name
        if self.footer and '3' in self.footer:
            players_data = self.footer['3']
            if isinstance(players_data, list):
                for p in players_data:
                    if not isinstance(p, dict):
                        continue
                    slot = p.get('1')
                    name = p.get('2')
                    if slot and isinstance(slot, int):
                        if slot not in self.players:
                            if name and isinstance(name, str):
                                self.players[slot] = name
                            else:
                                # Player exists but name is corrupted/missing
                                self.players[slot] = f"Player {slot}"

    def _extract_actions(self):
        """Extract all player actions"""
        for msg in self.messages:
            if not isinstance(msg, dict):
                continue
            frame = get_nested(msg, 1)
            pid = get_nested(msg, 2)
            content = get_nested(msg, 3, 1)

            if content is None or not isinstance(content, dict):
                continue

            for field_num, values in content.items():
                # Normalize to list - values may be a single entry or a list
                entries = values if isinstance(values, list) else [values]
                for entry in entries:
                    if entry['t'] != 'm':
                        continue

                    action = {
                        'frame': frame,
                        'time': frame_to_time(frame),
                        'player_id': pid,
                        'player': self.players.get(pid, f"P{pid}"),
                        'field': field_num,
                    }

                    data = entry['v']

                    # Store simplified raw data for all actions
                    action['raw'] = simplify_protobuf(
                        data,
                        include_bytes=self.include_bytes,
                        bytes_hex_limit=self.bytes_hex_limit,
                    )

                    # Categorize by field number (may be string or int)
                    field_num_int = int(field_num) if isinstance(field_num, str) else field_num
                    if field_num_int == 7:
                        action['type'] = 'COMMAND'
                        action['cmd_type'] = get_nested(data, 1)

                        # Extract target info (subfield 9) - entity IDs
                        field9 = pb_get(data, 9)
                        if field9:
                            entries9 = field9 if isinstance(field9, list) else [field9]
                            for sf9 in entries9:
                                if isinstance(sf9, dict) and sf9.get('t') == 'm':
                                    target_id = get_nested(sf9['v'], 1)
                                    target_type = get_nested(sf9['v'], 2)
                                    f3 = get_nested(sf9['v'], 3)
                                    f4 = get_nested(sf9['v'], 4)
                                    f5 = get_nested(sf9['v'], 5)
                                    f6 = get_nested(sf9['v'], 6)

                                    if target_id:
                                        action['target_id'] = target_id
                                    if target_type:
                                        action['target_type'] = target_type
                                        if self.ability_lookup:
                                            name, base_type = self.ability_lookup.get_full(target_type)
                                            if name != str(target_type):
                                                action['target_type_name'] = name

                                    # Include f3-f6 if non-zero
                                    if f3:
                                        action['target_f3'] = f3
                                    if f4:
                                        action['target_f4'] = f4
                                    if f5:
                                        action['target_f5'] = f5
                                    if f6:
                                        action['target_f6'] = f6

                                    # Decode fixed-point coordinates if present
                                    if f5 is not None and f6 is not None:
                                        x = _fixed_to_world(f5)
                                        y = _fixed_to_world(f6)
                                        if x is not None and y is not None:
                                            action['x'] = x
                                            action['y'] = y

                        # Extract ability info (subfield 4)
                        if pb_has(data, 4):
                            action['has_ability'] = True
                            ability_data = get_nested(data, 4)
                            if ability_data:
                                ability_id = get_nested(ability_data, 1)
                                action['ability_id'] = ability_id
                                if ability_id and self.ability_lookup:
                                    name, base_type = self.ability_lookup.get_full(ability_id)
                                    if name != str(ability_id):
                                        action['ability_name'] = name

                                # Extract build/spawn info from field 4 subfields
                                # f4.2 = position index (often build slot / UI ref)
                                # f4.3 = building/unit type (common for construction placement)
                                # f4.5/f4.6 appear to be generic flags/unknowns; DO NOT treat as a unit slot.
                                action['ability_pos_index'] = get_nested(ability_data, 2)
                                build_type = get_nested(ability_data, 3)
                                action['ability_f5'] = get_nested(ability_data, 5)
                                action['ability_f6'] = get_nested(ability_data, 6)

                                # Extract ability coordinates (4 -> 4 -> (1,2)) when present
                                coords = get_nested(ability_data, 4)
                                if isinstance(coords, dict):
                                    ax = get_nested(coords, 1)
                                    ay = get_nested(coords, 2)
                                    if ax is not None and ay is not None and action.get('x') is None:
                                        x = _fixed_to_world(ax)
                                        y = _fixed_to_world(ay)
                                        if x is not None and y is not None:
                                            action['x'] = x
                                            action['y'] = y

                                if build_type:
                                    action['build_type'] = build_type
                                    if self.ability_lookup:
                                        name, base_type = self.ability_lookup.get_full(build_type)
                                        if name != str(build_type):
                                            action['build_type_name'] = name

                    elif field_num_int == 4:
                        action['type'] = 'SPAWN'
                        action['owner'] = get_nested(data, 1)
                        action['unit_type'] = get_nested(data, 3)

                    elif field_num_int == 40:
                        action['type'] = 'SYNC'
                        # Extract sync values
                        for k, v in data.items():
                            val_list = v if isinstance(v, list) else [v]
                            if val_list and isinstance(val_list[0], dict) and val_list[0].get('t') == 'v':
                                action[f'sync_{k}'] = val_list[0]['v']
                        # Track max sync_1 for game duration (excludes loading time)
                        if action.get('sync_1') and action['sync_1'] > self.max_sync_time:
                            self.max_sync_time = action['sync_1']

                    elif field_num_int == 37:
                        action['type'] = 'PLAYER_JOIN'
                        action['name'] = get_nested(data, 3)
                        action['slot'] = get_nested(data, 2)

                    elif field_num_int == 45:
                        action['type'] = 'PROFILE'

                    else:
                        action['type'] = f'FIELD_{field_num_int}'

                    self.actions.append(action)

    def _extract_chat(self):
        """Extract chat messages"""
        skip_strings = set(self.players.values()) | {self.map_name, '', None}

        for msg in self.messages:
            if not isinstance(msg, dict):
                continue
            frame = get_nested(msg, 1)
            pid = get_nested(msg, 2)

            strings = find_all_strings(msg)
            for s in strings:
                if s not in skip_strings and len(s) > 3 and not s.startswith(':'):
                    self.chat.append({
                        'frame': frame,
                        'time': frame_to_time(frame),
                        'player_id': pid,
                        'player': self.players.get(pid, f"P{pid}"),
                        'text': s
                    })

    def report(self):
        """Print analysis report"""
        print("=" * 80)
        print("STORMGATE REPLAY ANALYSIS")
        print("=" * 80)

        # File info
        print(f"\nFile: {os.path.basename(self.filepath)}")
        print(f"Changelist: {self.header['changelist']}")
        print(f"Version: {self.header['version']}")
        print(f"Raw size: {len(self.raw_data):,} bytes")
        print(f"Messages: {len(self.messages):,}")
        if self.compressed_unused_len:
            trailer = ""
            if isinstance(self.gzip_trailer, dict):
                trailer = f" (gzip trailer isize={self.gzip_trailer.get('isize')}, crc32={self.gzip_trailer.get('crc32')})"
            print(f"Compressed unused bytes after deflate: {self.compressed_unused_len:,}{trailer}")
            if self.footer:
                # Surface any interesting strings in the footer
                footer_strings = find_all_strings(self.footer_protobuf) if self.footer_protobuf else []
                if footer_strings:
                    preview = ', '.join(footer_strings[:5])
                    more = f" (+{len(footer_strings) - 5} more)" if len(footer_strings) > 5 else ""
                    print(f"Footer protobuf strings: {preview}{more}")

        # Game info
        print(f"\n{'='*40}")
        print("GAME INFO")
        print(f"{'='*40}")
        print(f"Map: {self.map_name or 'Unknown'}")

        # Duration (use sync time which excludes loading)
        if self.max_sync_time > 0:
            duration_secs = self.max_sync_time / FRAME_RATE_HZ
            mins = int(duration_secs // 60)
            secs = int(duration_secs % 60)
            print(f"Duration: {mins}m {secs}s ({self.max_sync_time:,} ticks)")

        # Players
        print(f"\n{'='*40}")
        print("PLAYERS")
        print(f"{'='*40}")
        for slot, name in sorted(self.players.items()):
            print(f"  Slot {slot}: {name}")

        # Action counts
        print(f"\n{'='*40}")
        print("ACTION SUMMARY")
        print(f"{'='*40}")
        action_types = Counter(a['type'] for a in self.actions)
        for atype, count in sorted(action_types.items(), key=lambda x: -x[1])[:15]:
            print(f"  {atype:20}: {count:6}")

        # APM per player
        print(f"\n{'='*40}")
        print("APM (Actions Per Minute)")
        print(f"{'='*40}")
        player_actions = defaultdict(list)
        for a in self.actions:
            if a['type'] == 'COMMAND' and a['player_id'] in self.players:
                player_actions[a['player_id']].append(a['frame'])

        for pid in sorted(player_actions.keys()):
            frames = player_actions[pid]
            if len(frames) > 1:
                duration_mins = (max(frames) - min(frames)) / FRAME_RATE_HZ / 60  # ticks to minutes
                if duration_mins > 0:
                    apm = len(frames) / duration_mins
                    print(f"  {self.players[pid]:15}: {len(frames):5} actions, {apm:.0f} APM")

        # Chat
        print(f"\n{'='*40}")
        print("CHAT LOG")
        print(f"{'='*40}")
        if self.chat:
            for c in self.chat:
                print(f"  [{c['time']}] {c['player']:15}: {c['text']}")
        else:
            print("  (no chat messages)")

        # Position data summary
        if self.positions:
            xs = [p[2] for p in self.positions if p[2] == p[2]]
            ys = [p[3] for p in self.positions if p[3] == p[3]]
            print(f"\n{'='*40}")
            print("MAP/POSITION DATA")
            print(f"{'='*40}")
            print(f"  Position commands: {len(self.positions)}")
            if xs and ys:
                print(f"  Map bounds: X=[{min(xs):.0f}, {max(xs):.0f}]  Y=[{min(ys):.0f}, {max(ys):.0f}]")

        # Entity tracking
        print(f"\n{'='*40}")
        print("ENTITY TRACKING")
        print(f"{'='*40}")
        entities = self.entity_tracker.get_summary()
        print(f"Tracked {len(entities)} entities:")
        for e in entities[:10]:
            abilities = ', '.join(list(e['top_abilities'].keys())[:3])
            etype = e['inferred_type'] or 'Unknown'
            owner = e['owner'] or 'Unknown'
            print(f"  {e['target_id']:>12}: {etype:15} owner={owner:15} actions={e['action_count']:4}  [{abilities}]")

        # Target type stats
        print(f"\n{'='*40}")
        print("TARGET TYPE USAGE")
        print(f"{'='*40}")
        for name, count in self.target_type_stats.most_common(15):
            print(f"  {name:40}: {count:5}")

        # Ability stats
        print(f"\n{'='*40}")
        print("ABILITY USAGE")
        print(f"{'='*40}")
        for name, count in self.ability_id_stats.most_common(15):
            print(f"  {name:40}: {count:5}")

        # Timeline sample
        print(f"\n{'='*40}")
        print("ACTION TIMELINE (first 50)")
        print(f"{'='*40}")
        for a in self.actions[:50]:
            details = ""
            if a['type'] == 'SPAWN':
                details = f"unit_type={a.get('unit_type')}"
            elif a['type'] == 'COMMAND':
                if a.get('x') is not None:
                    details = f"pos=({a['x']:.0f}, {a['y']:.0f})"
                elif a.get('ability_name'):
                    details = f"ability={a['ability_name']}"
                elif a.get('ability_id'):
                    details = f"ability={a['ability_id']}"
                if a.get('target_type_name'):
                    details += f" target={a['target_type_name']}"
            print(f"  [{a['time']}] {a['player']:15} {a['type']:15} {details}")

    def get_game_result(self) -> dict:
        """Extract game result (winner/loser) from replay data.

        Returns dict with:
            - result: 'complete' if we have result data, 'unknown' otherwise
            - winners: list of player names who won
            - losers: list of player names who lost
            - player_results: dict mapping player slot (from game) to 'win' or 'loss'

        Detection method:
        1. Primary: Use Field 31 message which indicates the losing team
           (Field 31.1 contains slot of a player on losing team)
        2. Fallback: Use footer field 3 markers (less reliable)
        """
        result = {
            'result': 'unknown',
            'winners': [],
            'losers': [],
            'player_results': {}
        }

        if not self.footer or '3' not in self.footer:
            return result

        players_data = self.footer['3']
        if not isinstance(players_data, list):
            return result

        # Build player info: slot -> {name, team (f5)}
        slot_to_info = {}
        for p in players_data:
            if not isinstance(p, dict):
                continue
            slot = p.get('1')
            name = p.get('2')
            team = p.get('5')  # field 5 is team (may be None in older replays)
            if slot and isinstance(slot, int):
                slot_to_info[slot] = {
                    'name': name if isinstance(name, str) else f'Player {slot}',
                    'team': team
                }

        # Check if team information is useful (at least 2 different teams)
        teams = set(info['team'] for info in slot_to_info.values() if info['team'] is not None)
        has_valid_teams = len(teams) >= 2

        # Try to find Field 31 message to determine winning team
        winning_team = None
        if has_valid_teams:
            for msg in self.messages:
                content = get_nested(msg, 3, 1)
                if content and isinstance(content, dict):
                    # Check for field 31 (try both int and string keys)
                    field31 = content.get(31) or content.get('31')
                    if field31:
                        # field31 may be a single entry or a list
                        entries = field31 if isinstance(field31, list) else [field31]
                        for entry in entries:
                            if isinstance(entry, dict) and entry.get('t') == 'm':
                                # Field 31.1 is slot of player on WINNING team
                                winner_slot = get_nested(entry['v'], 1)
                                if winner_slot and winner_slot in slot_to_info:
                                    winning_team = slot_to_info[winner_slot]['team']
                                break
                        if winning_team is not None:
                            break

        # Determine winners/losers based on team
        if winning_team is not None:
            for slot, info in slot_to_info.items():
                name = info['name']
                if info['team'] == winning_team:
                    result['winners'].append(name)
                    result['player_results'][str(slot)] = 'win'
                else:
                    result['losers'].append(name)
                    result['player_results'][str(slot)] = 'loss'
        else:
            # Fallback: use footer field 3 markers
            for p in players_data:
                if not isinstance(p, dict):
                    continue
                slot = p.get('1')
                name = p.get('2')
                if not name or not isinstance(name, str):
                    name = f'Player {slot}' if slot else 'Unknown'
                # Field 3 = 1 indicates WIN, absence indicates loss
                is_winner = p.get('3') == 1
                if is_winner:
                    result['winners'].append(name)
                else:
                    result['losers'].append(name)
                if slot:
                    result['player_results'][str(slot)] = 'win' if is_winner else 'loss'

        # Map results to actual game slots by matching player names
        # self.players maps game_slot -> name (may differ from footer slots)
        name_to_result = {}
        for slot, res in result['player_results'].items():
            info = slot_to_info.get(int(slot))
            if info:
                name_to_result[info['name']] = res

        result['player_results'] = {}
        for game_slot, name in self.players.items():
            if name in name_to_result:
                result['player_results'][str(game_slot)] = name_to_result[name]

        if result['winners'] or result['losers']:
            result['result'] = 'complete'

        return result

    # Friendly names for common buildings/structures
    BUILDING_FRIENDLY_NAMES = {
        # Resource structures (all factions)
        'MegaResourceA': 'Supply',
        'ResourceB_LimitedAmount': 'Therium Deposit',
        'ResourceB_Generator_2x2': 'Therium Extractor',
        'ResourceB_Generator_3x3': 'Therium Extractor (Large)',
        # Vanguard
        'HQTier1': 'Command Post',
        'HQTier2': 'Command Post T2',
        'HQTier3': 'Command Post T3',
        'VanguardExpansionHQ': 'Expansion HQ',
        'MechBay': 'Mech Bay',
        'HangarBay': 'Hangar Bay',
        'AtlasBay': 'Atlas Bay',
        'SentryPost': 'Sentry Post',
        'ResearchLab': 'Research Lab',
        # Celestial
        'ArcshipTier1': 'Arcship',
        'ArcshipTier2': 'Arcship T2',
        'ArcshipTier3': 'Arcship T3',
        'CelestialExpansionHQ': 'Expansion Arcship',
        'CreationChamber': 'Creation Chamber',
        'KriNexus': 'Kri Nexus',
        'CabalNexus': 'Cabal Nexus',
        'GuardianNexus': 'Guardian Nexus',
        'CollectionArray': 'Collection Array',
        'LinkNode': 'Link Node',
        'ForceProjector': 'Force Projector',
        'Mainframe': 'Mainframe',
        'Bastion': 'Bastion',
        'MorphCore': 'Morph Core',
        'SparkNode': 'Spark Node',
        'WarpNode': 'Warp Node',
        # Infernal
        'Stormgate': 'Stormgate',
        'InfernalExpansionHQ': 'Expansion Stormgate',
        'LesserShrine': 'Shrine (Lesser)',
        'GreaterShrine': 'Shrine (Greater)',
        'ElderShrine': 'Shrine (Elder)',
        'IronVault': 'Iron Vault',
        'FiendVault': 'Fiend Vault',
        'BruteVault': 'Brute Vault',
        'Conclave': 'Conclave',
        'HexenConclave': 'Hexen Conclave',
        'TributePyre': 'Tribute Pyre',
        'RitualChamber': 'Ritual Chamber',
        # Map objectives (should be filtered but just in case)
        'StormgateObjectiveLv1': 'Stormgate Objective',
    }

    # Building base types that are actual structures (not units)
    BUILDING_BASE_TYPES = {'UnitData', 'ResourceData', 'ResourceGeneratorData'}

    # Mapping from Spawn ability names to building names for inferring implicit buildings
    # When a player uses a Spawn ability but never built that building, we infer they had it
    SPAWN_TO_BUILDING = {
        # Vanguard
        'BarracksSpawn': 'Barracks',
        'MechBaySpawn': 'Mech Bay',
        'HangarBaySpawn': 'Hangar Bay',
        'AtlasBaySpawn': 'Atlas Bay',
        'HQSpawn': 'Command Post',
        'WarforgeSpawn': 'Warforge',
        # Celestial
        'CreationChamber_Spawn': 'Creation Chamber',
        'Mainframe_Spawn': 'Mainframe',
        'Arcship_Spawn': 'Arcship',
        'MorphCore_Spawn': 'Morph Core',
        # Infernal
        'Shrine_Spawn': 'Shrine',
        'Conclave_Spawn': 'Conclave',
        'IronVault_Spawn': 'Iron Vault',
        'TwilightSpire_Spawn': 'Twilight Spire',
        'Stormgate_Spawn': 'Stormgate',
    }

    # Mapping from building names to their type IDs for inferred buildings
    BUILDING_NAME_TO_ID = {
        'Barracks': 597044510,
        'Mech Bay': 3945975384,
        'Command Post': 1393406673,
        'Arcship': None,  # Starting building, no ID needed
        'Stormgate': None,  # Starting building, no ID needed
    }

    def get_building_orders(self) -> dict:
        """Extract building construction order per player.

        Returns dict mapping player slot to list of building events, ordered by time.
        Each event contains:
            - frame: game tick when building was placed
            - time: formatted time string (mm:ss)
            - building_type: numeric ID of the building
            - building_name: resolved name (if available)
            - x, y: coordinates where building was placed (if available)

        Note: Only includes actual structures, not unit spawns.
        Deduplicates by position_index to count each building only once.
        """
        player_buildings = defaultdict(list)
        # Track seen buildings by (player_id, position_index, building_type) to deduplicate
        seen_buildings = set()

        for a in self.actions:
            # Only look at COMMAND actions with build_type
            if a.get('type') != 'COMMAND':
                continue
            if not a.get('build_type'):
                continue

            pid = a.get('player_id')
            if not pid or pid == 64 or not isinstance(pid, (int, str)):
                continue

            build_type = a.get('build_type')
            raw_name = a.get('build_type_name') or str(build_type)

            # Filter out non-building commands:
            # 1. Attack commands (attackData) target units and should be excluded
            ability_name = a.get('ability_name', '')
            if ability_name and ability_name in ('attackData', 'CloneCreation', 'CallToFightBaseFaction'):
                continue

            # 2. Use buildings.json lookup to filter to only known buildings
            # This excludes units like Scout, Fiend, Lancer, etc.
            if BUILDING_LOOKUP:
                building_entry = BUILDING_LOOKUP.get(build_type)
                if not building_entry:
                    continue  # Not a known building
                # Use the building name from the lookup
                raw_name = building_entry.get('id', raw_name)
            elif a.get('x') is None and self.ability_lookup:
                # Fallback: filter out non-building types when we have no coordinates
                entry = self.ability_lookup.get(build_type)
                if entry and entry.get('type') not in self.BUILDING_BASE_TYPES:
                    continue

            # Deduplicate by (player_id, position_index, building_type)
            # position_index (field 4.2) uniquely identifies each building placement
            # Multiple commands with same position_index are repeated clicks for same building
            pos_index = a.get('ability_pos_index')
            dedup_key = (pid, pos_index, build_type)
            if dedup_key in seen_buildings:
                continue
            seen_buildings.add(dedup_key)

            # Get friendly name if available
            friendly_name = self.BUILDING_FRIENDLY_NAMES.get(raw_name, raw_name)

            building = {
                'frame': a.get('frame'),
                'time': a.get('time'),
                'building_type': build_type,
                'building_name': friendly_name,
            }

            # Include coordinates if available
            if a.get('x') is not None:
                building['x'] = a['x']
                building['y'] = a['y']

            player_buildings[pid].append(building)

        # Sort each player's buildings by frame
        for pid in player_buildings:
            player_buildings[pid].sort(key=lambda b: b['frame'] or 0)

        # Infer implicit buildings from Spawn commands
        # If a player uses a Spawn ability (e.g., BarracksSpawn) but never built that building,
        # we infer they had it (either pre-built or the build command wasn't recorded)
        inferred_buildings = defaultdict(list)

        # First, collect all Spawn commands per player with their first occurrence time
        player_spawns = defaultdict(dict)  # pid -> {building_name: first_frame}

        for a in self.actions:
            if a.get('type') != 'COMMAND':
                continue

            pid = a.get('player_id')
            if not pid or pid == 64:
                continue

            # Check target_type_name for Spawn abilities
            target_type = a.get('target_type_name', '')
            if target_type in self.SPAWN_TO_BUILDING:
                building_name = self.SPAWN_TO_BUILDING[target_type]
                frame = a.get('frame') or 0

                # Record first spawn time for this building
                if building_name not in player_spawns[pid]:
                    player_spawns[pid][building_name] = frame
                else:
                    player_spawns[pid][building_name] = min(player_spawns[pid][building_name], frame)

        # Now check which spawns don't have corresponding builds
        for pid, spawns in player_spawns.items():
            # Get set of building names this player explicitly built
            built_names = set()
            for b in player_buildings.get(pid, []):
                built_names.add(b['building_name'])
                # Also add variants (e.g., "Shrine (Lesser)" matches "Shrine")
                base_name = b['building_name'].split(' (')[0]
                built_names.add(base_name)

            for building_name, first_frame in spawns.items():
                # Skip if player already built this building
                if building_name in built_names:
                    continue
                # Skip starting buildings (Command Post, Arcship, Stormgate)
                if building_name in ('Command Post', 'Arcship', 'Stormgate'):
                    continue

                # Check if this spawn occurred before any explicit build of this building
                earliest_build_frame = None
                for b in player_buildings.get(pid, []):
                    if b['building_name'] == building_name or b['building_name'].startswith(building_name):
                        earliest_build_frame = b['frame']
                        break

                # If spawn is before build (or no build exists), infer the building
                if earliest_build_frame is None or first_frame < earliest_build_frame:
                    # Calculate time string
                    time_sec = first_frame / FRAME_RATE_HZ
                    time_str = f"{int(time_sec // 60):02d}:{int(time_sec % 60):02d}"

                    inferred = {
                        'frame': first_frame,
                        'time': time_str,
                        'building_type': self.BUILDING_NAME_TO_ID.get(building_name),
                        'building_name': f"{building_name} [Inferred]",
                        'inferred': True,
                    }
                    inferred_buildings[pid].append(inferred)

        # Merge inferred buildings with explicit buildings
        result = {}
        for pid in set(list(player_buildings.keys()) + list(inferred_buildings.keys())):
            all_buildings = player_buildings.get(pid, []) + inferred_buildings.get(pid, [])
            all_buildings.sort(key=lambda b: b['frame'] or 0)
            result[pid] = all_buildings

        return result

    # Friendly names for upgrades/research
    UPGRADE_FRIENDLY_NAMES = {
        'MorphToGreaterShrine': 'Upgrade to Greater Shrine',
        'MorphToElderShrine': 'Upgrade to Elder Shrine',
        'MorphToHQTier2': 'Upgrade to HQ Tier 2',
        'MorphToHQTier3': 'Upgrade to HQ Tier 3',
        'Hellforge_Research': 'Hellforge Research',
        'MunitionsFactoryResearch': 'Munitions Factory Research',
        'ResearchLabResearch': 'Research Lab Research',
    }

    # Keywords that indicate an upgrade/research ability
    UPGRADE_KEYWORDS = ['Research', 'Upgrade', 'MorphTo', 'Tier2', 'Tier3']

    def get_player_upgrades(self) -> dict:
        """Extract upgrades/research per player.

        Returns dict mapping player slot to list of upgrade events, ordered by time.
        Each event contains:
            - frame: game tick when upgrade was started
            - time: formatted time string (mm:ss)
            - upgrade_id: numeric ability ID
            - upgrade_name: resolved name
        """
        player_upgrades = defaultdict(list)
        # Track seen upgrades by (player_id, ability_id) to deduplicate
        seen_upgrades = set()

        for a in self.actions:
            if a.get('type') != 'COMMAND':
                continue

            pid = a.get('player_id')
            if not pid or pid == 64 or not isinstance(pid, (int, str)):
                continue

            ability_name = a.get('ability_name') or ''
            ability_id = a.get('ability_id')

            # Check if this is an upgrade ability (but not a Stormgate reward)
            is_upgrade = any(kw in ability_name for kw in self.UPGRADE_KEYWORDS)
            is_stormgate = ability_name.startswith('StormgateAbility')
            if not is_upgrade or is_stormgate:
                continue

            # Deduplicate by (player_id, ability_id)
            dedup_key = (pid, ability_id)
            if dedup_key in seen_upgrades:
                continue
            seen_upgrades.add(dedup_key)

            # Get friendly name
            friendly_name = self.UPGRADE_FRIENDLY_NAMES.get(ability_name, ability_name)
            # Clean up the name if no friendly version
            if friendly_name == ability_name:
                friendly_name = ability_name.replace('_', ' ').replace('MorphTo', 'Upgrade to ')

            upgrade = {
                'frame': a.get('frame'),
                'time': a.get('time'),
                'upgrade_id': ability_id,
                'upgrade_name': friendly_name,
            }

            player_upgrades[pid].append(upgrade)

        # Sort each player's upgrades by frame
        result = {}
        for pid, upgrades in player_upgrades.items():
            upgrades.sort(key=lambda u: u['frame'] or 0)
            result[pid] = upgrades

        return result

    # Friendly names for Stormgate rewards
    STORMGATE_REWARD_NAMES = {
        'StormgateAbilityCreateTier1Healer': 'Tier 1: Healer',
        'StormgateAbilityCreateTier1Ooze': 'Tier 1: Ooze',
        'StormgateAbilityCreateTier1Frost': 'Tier 1: Frost',
        'StormgateAbilityCreateTier2Exploder': 'Tier 2: Exploder',
        'StormgateAbilityCreateTier2Fortress': 'Tier 2: Fortress',
        'StormgateAbilityCreateTier2Wisp': 'Tier 2: Wisp',
        'StormgateAbilityCreateTier3ShadowDemon': 'Tier 3: Shadow Demon',
        'StormgateAbilityCreateTier3Quake': 'Tier 3: Quake',
    }

    def get_stormgate_rewards(self) -> dict:
        """Extract Stormgate rewards chosen by each player.

        Returns dict mapping player slot to list of Stormgate reward events, ordered by time.
        Each event contains:
            - frame: game tick when reward was chosen
            - time: formatted time string (mm:ss)
            - reward_id: numeric ability ID
            - reward_name: resolved friendly name
        """
        player_rewards = defaultdict(list)
        # Track seen rewards by (player_id, ability_id) to deduplicate
        seen_rewards = set()

        for a in self.actions:
            if a.get('type') != 'COMMAND':
                continue

            pid = a.get('player_id')
            if not pid or pid == 64 or not isinstance(pid, (int, str)):
                continue

            ability_name = a.get('ability_name') or ''
            ability_id = a.get('ability_id')

            # Check if this is a Stormgate reward ability
            if not ability_name.startswith('StormgateAbility'):
                continue

            # Deduplicate by (player_id, ability_id)
            dedup_key = (pid, ability_id)
            if dedup_key in seen_rewards:
                continue
            seen_rewards.add(dedup_key)

            # Get friendly name
            friendly_name = self.STORMGATE_REWARD_NAMES.get(ability_name)
            if not friendly_name:
                # Parse from ability name: StormgateAbilityCreateTierXName -> Tier X: Name
                clean = ability_name.replace('StormgateAbilityCreate', '')
                # e.g. "Tier1Healer" -> "Tier 1: Healer"
                import re
                match = re.match(r'Tier(\d+)(.+)', clean)
                if match:
                    tier, name = match.groups()
                    friendly_name = f'Tier {tier}: {name}'
                else:
                    friendly_name = clean

            reward = {
                'frame': a.get('frame'),
                'time': a.get('time'),
                'reward_id': ability_id,
                'reward_name': friendly_name,
            }

            player_rewards[pid].append(reward)

        # Sort each player's rewards by frame
        result = {}
        for pid, rewards in player_rewards.items():
            rewards.sort(key=lambda r: r['frame'] or 0)
            result[pid] = rewards

        return result

    # Map spawn ability names to friendly building/unit source names
    SPAWN_FRIENDLY_NAMES = {
        # Vanguard
        'HQSpawn': 'Command Post',
        'BarracksSpawn': 'Barracks',
        'MechBaySpawn': 'Mech Bay',
        'HangarBaySpawn': 'Hangar Bay',
        'AtlasBaySpawn': 'Atlas Bay',
        'SentryPostSpawn': 'Sentry Post',
        # Celestial
        'Arcship_Spawn': 'Arcship',
        'CreationChamber_Spawn': 'Creation Chamber',
        'KriNexus_Spawn': 'Kri Nexus',
        'CabalNexus_Spawn': 'Cabal Nexus',
        'GuardianNexus_Spawn': 'Guardian Nexus',
        # Infernal
        'Shrine_Spawn': 'Shrine',
        'IronVault_Spawn': 'Iron Vault',
        'Conclave_Spawn': 'Conclave',
        'FiendVault_Spawn': 'Fiend Vault',
        'BruteVault_Spawn': 'Brute Vault',
        'HexenConclave_Spawn': 'Hexen Conclave',
    }

    def get_unit_production(self) -> dict:
        """Extract unit production per player.

        Note: Replay format only records spawn ability (e.g., 'Shrine_Spawn'),
        not the specific unit type trained. So we track production by building.

        Returns dict mapping player slot to list of production events, ordered by time.
        Each event contains:
            - frame: game tick when production was queued
            - time: formatted time string (mm:ss)
            - ability_id: spawn ability ID
            - building: building/source name (e.g., 'Shrine', 'Barracks')
        """
        player_production = defaultdict(list)

        for a in self.actions:
            if a.get('type') != 'COMMAND':
                continue

            pid = a.get('player_id')
            if not pid or pid == 64 or not isinstance(pid, (int, str)):
                continue

            ability_name = a.get('ability_name') or ''

            # Check if this is a spawn ability
            if 'Spawn' not in ability_name and 'spawn' not in ability_name:
                continue

            # Get friendly building name
            building_name = self.SPAWN_FRIENDLY_NAMES.get(ability_name)
            if not building_name:
                # Try to extract building name from ability (e.g., "Barracks_Spawn" -> "Barracks")
                building_name = ability_name.replace('_Spawn', '').replace('Spawn', '').replace('_', ' ')
                if not building_name:
                    building_name = ability_name

            production = {
                'frame': a.get('frame'),
                'time': a.get('time'),
                'ability_id': a.get('ability_id'),
                'building': building_name,
            }

            player_production[pid].append(production)

        # Sort each player's production by frame
        result = {}
        for pid, productions in player_production.items():
            productions.sort(key=lambda p: p['frame'] or 0)
            result[pid] = productions

        return result

    def get_production_summary(self) -> dict:
        """Get summarized unit production counts per player per building.

        Returns dict mapping player slot to dict of building -> count.
        """
        production = self.get_unit_production()
        result = {}

        for pid, productions in production.items():
            building_counts = defaultdict(int)
            for p in productions:
                building_counts[p['building']] += 1
            result[pid] = dict(building_counts)

        return result

    def get_player_factions(self) -> dict:
        """Detect player factions from abilities/buildings used.

        Detection is based on the first faction-specific ability/building each player uses.
        The main production buildings are definitive: Arcship=Celestial, Shrine=Infernal, Barracks/HQ=Vanguard.

        Returns dict mapping player slot (int) to faction name.
        Factions: 'Vanguard', 'Celestial', 'Infernal', or 'Unknown'
        """
        # Definitive faction markers (first match wins)
        VANGUARD_MARKERS = ['Barracks', 'MechBay', 'HQSpawn', 'HQTier', 'Bob_', 'Vulcan', 'Hedgehog', 'Atlas', 'Hornet', 'Helicarrier']
        CELESTIAL_MARKERS = ['Arcship', 'CreationChamber', 'Kri', 'Prism', 'Animancer', 'Saber', 'Vector', 'Celestial_', 'PowerSurge']
        INFERNAL_MARKERS = ['Shrine', 'IronVault', 'Conclave', 'Imp_', 'Fiend', 'Brute', 'Hexen', 'Spriggan', 'SummonEffigy', 'Hellborne']

        factions = {}

        for a in self.actions:
            pid = a.get('player_id')
            if not pid or pid == 64 or not isinstance(pid, (int, str)) or pid in factions:
                continue  # Skip system actions and already-detected players

            # Check ability_name and target_type_name
            for name in [a.get('ability_name'), a.get('target_type_name')]:
                if not name:
                    continue

                # Check for faction markers
                for marker in VANGUARD_MARKERS:
                    if marker in name:
                        factions[pid] = 'Vanguard'
                        break
                if pid in factions:
                    break

                for marker in CELESTIAL_MARKERS:
                    if marker in name:
                        factions[pid] = 'Celestial'
                        break
                if pid in factions:
                    break

                for marker in INFERNAL_MARKERS:
                    if marker in name:
                        factions[pid] = 'Infernal'
                        break
                if pid in factions:
                    break

        # Fill in Unknown for players without detected faction
        for pid in self.players.keys():
            pid_int = pid if isinstance(pid, int) else int(pid)
            if pid_int not in factions:
                factions[pid_int] = 'Unknown'

        return factions

    def get_player_teams(self) -> dict:
        """Get team assignment for each player.

        Returns dict mapping player_id (int) to team number (int).
        Team info comes from footer, mapped via player names.
        """
        # Build name -> team mapping from footer
        name_to_team = {}
        if self.footer and '3' in self.footer:
            for p in self.footer['3']:
                if not isinstance(p, dict):
                    print(f"[DEBUG] Unexpected non-dict in footer['3']: {type(p).__name__} = {repr(p)}")
                    continue
                name = p.get('2')
                team = p.get('5')
                # Skip if name was incorrectly decoded as nested message instead of string
                if not isinstance(name, str):
                    continue
                if name and team:
                    name_to_team[name] = team

        # Map player_id to team using our players dict
        player_teams = {}
        for pid, name in self.players.items():
            team = name_to_team.get(name)
            if team:
                player_teams[pid] = team

        return player_teams

    def to_json(self, include_actions: bool = False, *, include_messages: bool = False) -> dict:
        """Export as JSON-serializable dict"""
        game_result = self.get_game_result()
        player_factions = self.get_player_factions()
        building_orders = self.get_building_orders()
        player_upgrades = self.get_player_upgrades()
        stormgate_rewards = self.get_stormgate_rewards()
        player_teams = self.get_player_teams()
        result = {
            'file': os.path.basename(self.filepath),
            'header': self.header,
            'map': self.map_name,
            'players': self.players,
            # Player teams (from footer)
            'player_teams': player_teams,
            # Player factions (detected from abilities used)
            'player_factions': player_factions,
            # Game result (winner/loser)
            'game_result': game_result,
            # Building construction order per player
            'building_orders': building_orders,
            # Upgrades/research per player
            'player_upgrades': player_upgrades,
            # Stormgate rewards chosen per player
            'stormgate_rewards': stormgate_rewards,
            # Unit production per player (summarized by building)
            'unit_production': self.get_production_summary(),
            # Detailed unit production timeline
            'unit_production_timeline': self.get_unit_production(),
            'raw_size_bytes': len(self.raw_data) if self.raw_data is not None else 0,
            'total_messages': len(self.messages),
            'total_actions': len(self.actions),
            'action_types': dict(Counter(a['type'] for a in self.actions)),
            'chat': self.chat,
            'duration_seconds': self.max_sync_time / FRAME_RATE_HZ if self.max_sync_time > 0 else 0,
            'target_type_stats': dict(self.target_type_stats.most_common()),
            'ability_stats': dict(self.ability_id_stats.most_common()),
            'entities': self.entity_tracker.to_dict(),
            # Compression/footer metadata (helps verify completeness and captures extra replay metadata)
            'gzip_header_len': self.gzip_header_len,
            'gzip_trailer': self.gzip_trailer,
            'compressed_unused_bytes': self.compressed_unused_len,
            'footer': self.footer,
        }

        if include_messages:
            # Full decoded protobuf message stream (can be large on real replays)
            result['messages'] = [
                simplify_protobuf(
                    m,
                    include_bytes=self.include_bytes,
                    bytes_hex_limit=self.bytes_hex_limit,
                )
                for m in self.messages
            ]

        if include_actions:
            # Clean up actions for JSON serialization
            clean_actions = []
            for a in self.actions:
                clean_a = {
                    'frame': a.get('frame'),
                    'time': a.get('time'),
                    'player_id': a.get('player_id'),
                    'player': a.get('player'),
                    'type': a.get('type'),
                }
                # Add type-specific fields
                if a.get('x') is not None:
                    clean_a['x'] = a['x']
                    clean_a['y'] = a['y']
                if a.get('ability_id'):
                    clean_a['ability_id'] = a['ability_id']
                if a.get('ability_name'):
                    clean_a['ability_name'] = a['ability_name']
                if a.get('unit_type'):
                    clean_a['unit_type'] = a['unit_type']
                if a.get('owner'):
                    clean_a['owner'] = a['owner']
                if a.get('cmd_type'):
                    clean_a['cmd_type'] = a['cmd_type']
                if a.get('target_id'):
                    clean_a['target_id'] = a['target_id']
                if a.get('target_type'):
                    clean_a['target_type'] = a['target_type']
                if a.get('target_type_name'):
                    clean_a['target_type_name'] = a['target_type_name']
                # Include target subfields f3-f6
                if a.get('target_f3'):
                    clean_a['target_f3'] = a['target_f3']
                if a.get('target_f4'):
                    clean_a['target_f4'] = a['target_f4']
                if a.get('target_f5'):
                    clean_a['target_f5'] = a['target_f5']
                if a.get('target_f6'):
                    clean_a['target_f6'] = a['target_f6']
                # Include build/spawn info
                if a.get('build_type'):
                    clean_a['build_type'] = a['build_type']
                if a.get('build_type_name'):
                    clean_a['build_type_name'] = a['build_type_name']
                if a.get('ability_pos_index') is not None:
                    clean_a['ability_pos_index'] = a['ability_pos_index']
                if a.get('ability_f5') is not None:
                    clean_a['ability_f5'] = a['ability_f5']
                if a.get('ability_f6') is not None:
                    clean_a['ability_f6'] = a['ability_f6']
                # Include sync data
                for key in a:
                    if key.startswith('sync_'):
                        clean_a[key] = a[key]
                # Include raw data
                if a.get('raw'):
                    clean_a['raw'] = a['raw']
                clean_actions.append(clean_a)
            result['actions'] = clean_actions

        return result

    def export_actions_json(self, output_path: str, *, include_messages: bool = False):
        """Export all actions to a JSON file"""
        # NOTE: include_messages is controlled by CLI; default is False to keep files small.
        data = self.to_json(include_actions=True, include_messages=include_messages)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        return output_path

def main():
    import argparse
    import io

    # Fix Windows encoding
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    arg_parser = argparse.ArgumentParser(
        description='Parse Stormgate replay files (.SGReplay)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python parse_sgreplay.py replay.SGReplay
  python parse_sgreplay.py replay.SGReplay --json
  python parse_sgreplay.py replay.SGReplay --json --output actions.json

Note: Resources are not stored in replay files. Replays are command-based
(like StarCraft 2) - they record player inputs, not game state.
        """
    )
    arg_parser.add_argument('replay', help='Path to .SGReplay file')
    arg_parser.add_argument('--json', action='store_true',
                           help='Export all actions to JSON')
    arg_parser.add_argument('--output', '-o',
                           help='Output JSON file path (default: <replay>_actions.json)')
    arg_parser.add_argument('--quiet', '-q', action='store_true',
                           help='Suppress console output (only export JSON)')
    arg_parser.add_argument('--no-lookup', action='store_true',
                           help='Disable ability name lookup')
    arg_parser.add_argument('--include-bytes', action='store_true',
                           help='Include a truncated hex preview for unknown byte blobs in exported raw protobuf')
    arg_parser.add_argument('--bytes-hex-limit', type=int, default=64,
                           help='Max bytes to include (as hex) per blob when --include-bytes is set (default: 64)')
    arg_parser.add_argument('--include-messages', action='store_true',
                           help='Include the full decoded protobuf message stream in exported JSON (can be large)')

    args = arg_parser.parse_args()

    if not os.path.exists(args.replay):
        print(f"Error: File not found: {args.replay}")
        sys.exit(1)

    # Load ability lookup if available
    ability_lookup = None
    if ABILITY_LOOKUP_AVAILABLE and not args.no_lookup:
        try:
            ability_lookup = AbilityLookup()
            if not args.quiet:
                print(f"Loaded ability lookup ({len(ability_lookup.lookup):,} entries)")
        except Exception as e:
            if not args.quiet:
                print(f"Warning: Could not load ability lookup: {e}")

    parser = SGReplayParser(
        args.replay,
        ability_lookup=ability_lookup,
        include_bytes=args.include_bytes,
        bytes_hex_limit=args.bytes_hex_limit,
    )
    parser.load().parse()

    if not args.quiet:
        parser.report()

    # Export JSON
    if args.json:
        json_path = args.output or args.replay.rsplit('.', 1)[0] + '_actions.json'
        data = parser.to_json(include_actions=True, include_messages=args.include_messages)
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        print(f"\nExported {len(parser.actions):,} actions to: {json_path}")
    else:
        # Just export summary
        json_path = args.replay.rsplit('.', 1)[0] + '_summary.json'
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(parser.to_json(include_messages=args.include_messages), f, indent=2, default=str)
        if not args.quiet:
            print(f"\nExported summary to: {json_path}")

if __name__ == '__main__':
    main()
