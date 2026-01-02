#!/usr/bin/env python3
"""
Ability/Target Type Lookup for Stormgate Replays

Maps numeric ability_id and target_type values from replays to human-readable names
using data from runtime_session.json.

Usage:
    python ability_lookup.py                    # Build and show stats
    python ability_lookup.py <replay.SGReplay>  # Analyze a replay with named abilities
"""

import json
import os
import sys
from collections import Counter
from typing import Dict, Optional, Tuple

RUNTIME_SESSION_PATH = os.path.join(os.path.dirname(__file__), 'runtime_session.json')


class AbilityLookup:
    """Lookup table for ability/target type IDs to names."""

    def __init__(self, runtime_session_path: str = RUNTIME_SESSION_PATH):
        self.lookup: Dict[int, dict] = {}
        self.by_hash: Dict[int, dict] = {}
        self._load(runtime_session_path)

    def _load(self, path: str):
        """Load and index the runtime_session.json file."""
        with open(path, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)

        archetypes = data.get('archetypes', {})

        for key, value in archetypes.items():
            if isinstance(value, list) and len(value) >= 2 and isinstance(value[1], dict):
                key_int = int(key)
                info = value[1]
                entry = {
                    'id': info.get('id', 'unknown'),
                    'type': info.get('__base_type', 'unknown'),
                    'hash': value[0],
                    'key': key_int,
                }
                self.lookup[key_int] = entry
                if isinstance(value[0], int):
                    self.by_hash[value[0]] = entry

    def get(self, type_id: int) -> Optional[dict]:
        """Look up an ability/target type by ID."""
        # Try direct key lookup first
        if type_id in self.lookup:
            return self.lookup[type_id]
        # Try hash lookup
        if type_id in self.by_hash:
            return self.by_hash[type_id]
        return None

    def get_name(self, type_id: int) -> str:
        """Get the name for a type ID, or return the ID as string if not found."""
        entry = self.get(type_id)
        if entry:
            return entry['id']
        return str(type_id)

    def get_full(self, type_id: int) -> Tuple[str, str]:
        """Get (name, base_type) for a type ID."""
        entry = self.get(type_id)
        if entry:
            return (entry['id'], entry['type'])
        return (str(type_id), 'unknown')

    def stats(self) -> dict:
        """Get statistics about the lookup table."""
        types = Counter(e['type'] for e in self.lookup.values())
        return {
            'total_entries': len(self.lookup),
            'by_type': dict(types.most_common(20)),
        }


def analyze_replay(replay_path: str, lookup: AbilityLookup):
    """Analyze a replay and show ability/target mappings."""
    from parse_sgreplay import SGReplayParser

    parser = SGReplayParser(replay_path)
    parser.load().parse()

    # Collect stats
    target_types = Counter()
    ability_ids = Counter()

    for action in parser.actions:
        if action.get('target_type'):
            target_types[action['target_type']] += 1
        if action.get('ability_id'):
            ability_ids[action['ability_id']] += 1

    print(f"\n{'='*80}")
    print(f"REPLAY ANALYSIS: {os.path.basename(replay_path)}")
    print(f"{'='*80}")

    print(f"\nTop Target Types:")
    print(f"{'-'*80}")
    print(f"{'ID':>12}  {'Count':>6}  {'Name':40}  {'Type'}")
    print(f"{'-'*80}")
    for tt, count in target_types.most_common(25):
        name, base_type = lookup.get_full(tt)
        print(f"{tt:>12}  {count:>6}  {name:40}  {base_type}")

    print(f"\nTop Ability IDs:")
    print(f"{'-'*80}")
    print(f"{'ID':>12}  {'Count':>6}  {'Name':40}  {'Type'}")
    print(f"{'-'*80}")
    for aid, count in ability_ids.most_common(25):
        name, base_type = lookup.get_full(aid)
        print(f"{aid:>12}  {count:>6}  {name:40}  {base_type}")

    # Coverage stats
    found_targets = sum(1 for tt in target_types if lookup.get(tt))
    found_abilities = sum(1 for aid in ability_ids if lookup.get(aid))
    print(f"\nCoverage:")
    print(f"  Target types: {found_targets}/{len(target_types)} ({100*found_targets/len(target_types):.1f}%)")
    print(f"  Ability IDs:  {found_abilities}/{len(ability_ids)} ({100*found_abilities/len(ability_ids):.1f}%)")


def main():
    print("Loading runtime_session.json...")
    lookup = AbilityLookup()

    stats = lookup.stats()
    print(f"Loaded {stats['total_entries']:,} entries")
    print(f"\nTop entry types:")
    for etype, count in list(stats['by_type'].items())[:10]:
        print(f"  {etype}: {count}")

    if len(sys.argv) > 1:
        replay_path = sys.argv[1]
        if os.path.exists(replay_path):
            analyze_replay(replay_path, lookup)
        else:
            print(f"Error: File not found: {replay_path}")
            sys.exit(1)
    else:
        print("\nUsage: python ability_lookup.py <replay.SGReplay>")
        print("\nExample lookups:")
        test_ids = [1318043485, 1485475066, 335308633, 3191913349, 890022063]
        for tid in test_ids:
            name, btype = lookup.get_full(tid)
            status = "FOUND" if lookup.get(tid) else "NOT FOUND"
            print(f"  {tid}: {name} ({btype}) [{status}]")


if __name__ == '__main__':
    main()
