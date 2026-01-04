"""
Entity tracking for Stormgate replay parsing.
Tracks units and buildings by their target_id throughout a game.
"""

from collections import Counter
from typing import Any, Dict, List, Optional


class EntityTracker:
    """Tracks entities (units/buildings) by their target_id throughout a game."""

    def __init__(self, ability_lookup=None):
        self.entities: Dict[Any, Dict] = {}  # target_id -> entity info
        self.ability_lookup = ability_lookup

    def _get_ability_name(self, ability_id) -> Optional[str]:
        """Get ability name from lookup."""
        if self.ability_lookup and ability_id:
            name, _ = self.ability_lookup.get_full(ability_id)
            if name != str(ability_id):
                return name
        return None

    def record_action(self, action: dict):
        """Record an action involving an entity."""
        target_id = action.get('target_id')
        if not target_id or not isinstance(target_id, (int, str)):
            return

        if target_id not in self.entities:
            self.entities[target_id] = {
                'id': target_id,
                'first_seen': action.get('frame'),
                'first_seen_time': action.get('time'),
                'last_seen': action.get('frame'),
                'last_seen_time': action.get('time'),
                'players': set(),
                'abilities_used': Counter(),  # abilities used ON this entity
                'abilities_cast': Counter(),  # abilities cast BY this entity
                'target_types': Counter(),
                'action_count': 0,
                'inferred_type': None,
                'inferred_owner': None,
            }

        entity = self.entities[target_id]
        entity['last_seen'] = action.get('frame')
        entity['last_seen_time'] = action.get('time')
        entity['action_count'] += 1

        player_id = action.get('player_id')
        if player_id and isinstance(player_id, (int, str)):
            entity['players'].add(player_id)

        # Track target_type (ability used on this entity)
        target_type = action.get('target_type')
        if target_type:
            name = action.get('target_type_name') or self._get_ability_name(target_type) or str(target_type)
            entity['target_types'][name] += 1
            entity['abilities_used'][name] += 1

        # Track ability_id (ability cast, possibly by this entity)
        ability_id = action.get('ability_id')
        if ability_id:
            name = action.get('ability_name') or self._get_ability_name(ability_id) or str(ability_id)
            entity['abilities_cast'][name] += 1

        # Try to infer entity type from abilities
        self._infer_type(entity)

    def _infer_type(self, entity: dict):
        """Infer what type of entity this is based on abilities used."""
        # Look for spawn abilities which indicate building type
        spawn_indicators = {
            'HQSpawn': 'HQ',
            'Shrine_Spawn': 'Shrine',
            'BarracksSpawn': 'Barracks',
            'IronVault_Spawn': 'IronVault',
            'CreationChamber_Spawn': 'CreationChamber',
            'Arcship_Spawn': 'Arcship',
            'Conclave_Spawn': 'Conclave',
        }

        morph_indicators = {
            'ArcshipTier1Land': 'Arcship',
            'ArcshipTier1Liftoff': 'Arcship',
            'MorphToArcshipTier2': 'Arcship',
            'MorphToArcshipTier3': 'Arcship',
            'MorphToHQTier2': 'HQ',
            'MorphToGreaterShrine': 'Shrine',
        }

        construct_indicators = {
            'WorkerConstructAbilityData': 'Worker',
            'Imp_Construct': 'Imp',
            'Celestial_Construct': 'Celestial',
        }

        # Check abilities used on this entity
        for ability, count in entity['abilities_used'].items():
            if ability in spawn_indicators:
                entity['inferred_type'] = spawn_indicators[ability]
                return
            if ability in morph_indicators:
                entity['inferred_type'] = morph_indicators[ability]
                return

        # Check abilities cast by this entity
        for ability, count in entity['abilities_cast'].items():
            if ability in spawn_indicators:
                entity['inferred_type'] = spawn_indicators[ability]
                return
            if ability in construct_indicators:
                entity['inferred_type'] = construct_indicators[ability]
                return

        # If mostly attack actions, probably a combat unit
        if entity['abilities_used'].get('attackData', 0) > entity['action_count'] * 0.5:
            entity['inferred_type'] = 'CombatUnit'

    def infer_owners(self, players: dict):
        """Infer entity owners based on which player uses them most."""
        for entity in self.entities.values():
            if entity['players']:
                # Most frequent player is likely the owner
                player_counts = Counter()
                for pid in entity['players']:
                    player_counts[pid] += 1
                most_common = player_counts.most_common(1)
                if most_common:
                    pid = most_common[0][0]
                    entity['inferred_owner'] = pid
                    entity['owner_name'] = players.get(pid, f'P{pid}')

    def get_summary(self) -> List[dict]:
        """Get a summary of all tracked entities."""
        summaries = []
        for target_id, entity in sorted(self.entities.items(), key=lambda x: -x[1]['action_count']):
            summary = {
                'target_id': target_id,
                'inferred_type': entity.get('inferred_type', 'Unknown'),
                'owner': entity.get('owner_name', 'Unknown'),
                'first_seen': entity['first_seen_time'],
                'last_seen': entity['last_seen_time'],
                'action_count': entity['action_count'],
                'top_abilities': dict(entity['abilities_used'].most_common(5)),
            }
            summaries.append(summary)
        return summaries

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        result = {}
        for target_id, entity in self.entities.items():
            result[str(target_id)] = {
                'target_id': target_id,
                'inferred_type': entity.get('inferred_type'),
                'inferred_owner': entity.get('inferred_owner'),
                'owner_name': entity.get('owner_name'),
                'first_seen': entity['first_seen'],
                'first_seen_time': entity['first_seen_time'],
                'last_seen': entity['last_seen'],
                'last_seen_time': entity['last_seen_time'],
                'action_count': entity['action_count'],
                'players': list(entity['players']),
                'abilities_used': dict(entity['abilities_used']),
                'abilities_cast': dict(entity['abilities_cast']),
                'target_types': dict(entity['target_types']),
            }
        return result
