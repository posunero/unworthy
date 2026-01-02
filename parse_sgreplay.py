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

# Frame values appear to be in milliseconds based on analysis
# (not game ticks - typical game is 10-30 mins, not 3+ hours)
FRAME_UNIT_MS = True  # Frame values are milliseconds

def decode_varint(data: bytes, pos: int) -> Tuple[int, int]:
    result = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        result |= (b & 0x7f) << shift
        pos += 1
        if (b & 0x80) == 0:
            break
        shift += 7
    return result, pos

def decode_message(data: bytes, depth: int = 0) -> Optional[Dict]:
    if depth > 15 or len(data) == 0:
        return None
    fields = defaultdict(list)
    pos = 0
    end = len(data)
    while pos < end:
        try:
            tag, pos = decode_varint(data, pos)
            if tag == 0:
                break
            field_num = tag >> 3
            wire_type = tag & 0x7
            if field_num == 0 or field_num > 50000:
                break
            if wire_type == 0:
                value, pos = decode_varint(data, pos)
                fields[field_num].append({'t': 'v', 'v': value})
            elif wire_type == 1:
                if pos + 8 > end:
                    break
                raw = data[pos:pos+8]
                pos += 8
                fields[field_num].append({'t': 'f64', 'd': struct.unpack('<d', raw)[0], 'i': struct.unpack('<q', raw)[0]})
            elif wire_type == 2:
                length, pos = decode_varint(data, pos)
                if length > end - pos or length < 0:
                    break
                raw = data[pos:pos+length]
                pos += length
                try:
                    s = raw.decode('utf-8')
                    if all(c.isprintable() or c in '\n\r\t ' for c in s):
                        fields[field_num].append({'t': 's', 'v': s})
                        continue
                except:
                    pass
                nested = decode_message(raw, depth + 1)
                if nested:
                    fields[field_num].append({'t': 'm', 'v': nested})
                else:
                    fields[field_num].append({'t': 'b', 'len': len(raw), 'raw': raw})
            elif wire_type == 5:
                if pos + 4 > end:
                    break
                raw = data[pos:pos+4]
                pos += 4
                fields[field_num].append({'t': 'f32', 'f': struct.unpack('<f', raw)[0], 'i': struct.unpack('<i', raw)[0]})
            else:
                break
        except:
            break
    return dict(fields) if fields else None

def get_nested(msg: Dict, *path) -> Any:
    current = msg
    for p in path:
        if not isinstance(current, dict) or p not in current:
            return None
        vals = current[p]
        if not vals:
            return None
        entry = vals[0]
        if entry['t'] == 'm':
            current = entry['v']
        elif entry['t'] in ('v', 's'):
            return entry['v']
        else:
            return entry
    return current

def find_all_strings(obj, depth=0):
    results = []
    if depth > 15:
        return results
    if isinstance(obj, dict):
        for v in obj.values():
            results.extend(find_all_strings(v, depth+1))
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict):
                if item.get('t') == 's' and item.get('v'):
                    results.append(item['v'])
                else:
                    results.extend(find_all_strings(item, depth+1))
    return results

def frame_to_time(frame: int) -> str:
    """Convert frame number to mm:ss format"""
    if frame is None:
        return "00:00"
    # Frame values are in milliseconds
    total_secs = frame / 1000
    mins = int(total_secs // 60)
    secs = int(total_secs % 60)
    return f"{mins:02d}:{secs:02d}"

def frame_to_seconds(frame: int) -> float:
    """Convert frame to seconds"""
    if frame is None:
        return 0
    return frame / 1000

class SGReplayParser:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.header = {}
        self.messages = []
        self.players = {}
        self.actions = []
        self.chat = []
        self.positions = []
        self.map_name = None

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
            compressed = f.read()

        # Decompress (skip 10-byte gzip header)
        decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
        self.raw_data = decompressor.decompress(compressed[10:])
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
            decoded = decode_message(msg_data)
            if decoded:
                self.messages.append(decoded)

        self._extract_game_info()
        self._extract_actions()
        self._extract_chat()
        return self

    def _extract_game_info(self):
        """Extract map name and player info"""
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

            # Player info from field 37
            if 37 in content:
                for entry in content[37]:
                    if entry['t'] == 'm':
                        slot = get_nested(entry['v'], 2)
                        name = get_nested(entry['v'], 3)
                        if slot and name:
                            self.players[slot] = name

            # Player info from field 45 (profile data)
            if 45 in content and pid and pid not in self.players:
                for entry in content[45]:
                    if entry['t'] == 'm':
                        # Path: 45 -> 5 -> 1 = name, 5 -> 2 = player ID string
                        name = get_nested(entry['v'], 5, 1)
                        if name and isinstance(name, str):
                            self.players[pid] = name

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
                for entry in values:
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

                    # Categorize by field number
                    if field_num == 7:
                        action['type'] = 'COMMAND'
                        action['cmd_type'] = get_nested(data, 1)

                        # Extract target info (subfield 9) - entity IDs
                        if 9 in data:
                            for sf9 in data[9]:
                                if sf9['t'] == 'm':
                                    target_id = get_nested(sf9['v'], 1)
                                    target_type = get_nested(sf9['v'], 2)
                                    if target_id:
                                        action['target_id'] = target_id
                                    if target_type:
                                        action['target_type'] = target_type

                        # Extract ability info (subfield 4)
                        if 4 in data:
                            action['has_ability'] = True
                            ability_data = get_nested(data, 4)
                            if ability_data:
                                action['ability_id'] = get_nested(ability_data, 1)

                    elif field_num == 4:
                        action['type'] = 'SPAWN'
                        action['owner'] = get_nested(data, 1)
                        action['unit_type'] = get_nested(data, 3)

                    elif field_num == 40:
                        action['type'] = 'SYNC'
                        # Extract sync values
                        for k, v in data.items():
                            if v and v[0]['t'] == 'v':
                                action[f'sync_{k}'] = v[0]['v']

                    elif field_num == 37:
                        action['type'] = 'PLAYER_JOIN'
                        action['name'] = get_nested(data, 3)
                        action['slot'] = get_nested(data, 2)

                    elif field_num == 45:
                        action['type'] = 'PROFILE'

                    else:
                        action['type'] = f'FIELD_{field_num}'

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

        # Game info
        print(f"\n{'='*40}")
        print("GAME INFO")
        print(f"{'='*40}")
        print(f"Map: {self.map_name or 'Unknown'}")

        # Duration
        frames = [a['frame'] for a in self.actions if a['frame']]
        if frames:
            max_frame = max(frames)
            duration_secs = max_frame / 1000  # milliseconds to seconds
            mins = int(duration_secs // 60)
            secs = int(duration_secs % 60)
            print(f"Duration: {mins}m {secs}s ({max_frame:,} ms)")

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
                duration_mins = (max(frames) - min(frames)) / 1000 / 60  # ms to minutes
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
                elif a.get('ability_id'):
                    details = f"ability={a['ability_id']}"
            print(f"  [{a['time']}] {a['player']:15} {a['type']:15} {details}")

    def to_json(self, include_actions: bool = False) -> dict:
        """Export as JSON-serializable dict"""
        result = {
            'file': os.path.basename(self.filepath),
            'header': self.header,
            'map': self.map_name,
            'players': self.players,
            'total_messages': len(self.messages),
            'total_actions': len(self.actions),
            'action_types': dict(Counter(a['type'] for a in self.actions)),
            'chat': self.chat,
            'duration_seconds': max((a['frame'] or 0) for a in self.actions) / 1000 if self.actions else 0,
        }

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
                # Include sync data
                for key in a:
                    if key.startswith('sync_'):
                        clean_a[key] = a[key]
                clean_actions.append(clean_a)
            result['actions'] = clean_actions

        return result

    def export_actions_json(self, output_path: str):
        """Export all actions to a JSON file"""
        data = self.to_json(include_actions=True)
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

    args = arg_parser.parse_args()

    if not os.path.exists(args.replay):
        print(f"Error: File not found: {args.replay}")
        sys.exit(1)

    parser = SGReplayParser(args.replay)
    parser.load().parse()

    if not args.quiet:
        parser.report()

    # Export JSON
    if args.json:
        json_path = args.output or args.replay.rsplit('.', 1)[0] + '_actions.json'
        parser.export_actions_json(json_path)
        print(f"\nExported {len(parser.actions):,} actions to: {json_path}")
    else:
        # Just export summary
        json_path = args.replay.rsplit('.', 1)[0] + '_summary.json'
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(parser.to_json(), f, indent=2, default=str)
        if not args.quiet:
            print(f"\nExported summary to: {json_path}")

if __name__ == '__main__':
    main()
