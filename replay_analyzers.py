"""
Replay analysis functions for extracting game statistics.
These functions operate on parsed replay data.
"""

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

# Frame rate constant
FRAME_RATE_HZ = 1024


def frame_to_time(frame: int) -> str:
    """Convert frame number to mm:ss format"""
    if frame is None:
        return "00:00"
    total_secs = frame / FRAME_RATE_HZ
    mins = int(total_secs // 60)
    secs = int(total_secs % 60)
    return f"{mins:02d}:{secs:02d}"


def frame_to_seconds(frame: int) -> float:
    """Convert frame to seconds"""
    if frame is None:
        return 0
    return frame / FRAME_RATE_HZ


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


def extract_player_upgrades(actions: List[dict]) -> dict:
    """Extract upgrades/research per player from actions.

    Returns dict mapping player slot to list of upgrade events, ordered by time.
    """
    player_upgrades = defaultdict(list)
    seen_upgrades = set()

    for a in actions:
        if a.get('type') != 'COMMAND':
            continue

        pid = a.get('player_id')
        if not pid or pid == 64 or not isinstance(pid, (int, str)):
            continue

        ability_name = a.get('ability_name') or ''
        ability_id = a.get('ability_id')

        # Check if this is an upgrade ability (but not a Stormgate reward)
        is_upgrade = any(kw in ability_name for kw in UPGRADE_KEYWORDS)
        is_stormgate = ability_name.startswith('StormgateAbility')
        if not is_upgrade or is_stormgate:
            continue

        # Deduplicate by (player_id, ability_id)
        dedup_key = (pid, ability_id)
        if dedup_key in seen_upgrades:
            continue
        seen_upgrades.add(dedup_key)

        # Get friendly name
        friendly_name = UPGRADE_FRIENDLY_NAMES.get(ability_name, ability_name)
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


def extract_stormgate_rewards(actions: List[dict]) -> dict:
    """Extract Stormgate rewards chosen by each player from actions.

    Returns dict mapping player slot to list of reward events, ordered by time.
    """
    player_rewards = defaultdict(list)
    seen_rewards = set()

    for a in actions:
        if a.get('type') != 'COMMAND':
            continue

        pid = a.get('player_id')
        if not pid or pid == 64 or not isinstance(pid, (int, str)):
            continue

        ability_name = a.get('ability_name') or ''
        ability_id = a.get('ability_id')

        if not ability_name.startswith('StormgateAbility'):
            continue

        # Deduplicate by (player_id, ability_id)
        dedup_key = (pid, ability_id)
        if dedup_key in seen_rewards:
            continue
        seen_rewards.add(dedup_key)

        # Get friendly name
        friendly_name = STORMGATE_REWARD_NAMES.get(ability_name)
        if not friendly_name:
            clean = ability_name.replace('StormgateAbilityCreate', '')
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


def extract_game_result(footer: Optional[dict], players: dict) -> dict:
    """Extract game result from footer data.

    Returns dict with:
        - result: 'complete', 'incomplete', or 'unknown'
        - winners: list of winner names
        - losers: list of loser names
        - player_results: dict mapping player slot to 'win' or 'loss'
        - winner_team: winning team number (if applicable)
    """
    result = {
        'result': 'unknown',
        'winners': [],
        'losers': [],
        'player_results': {},
        'winner_team': None,
    }

    if not footer:
        return result

    # Get player results from footer field 3
    footer_players = footer.get('3', [])
    if not isinstance(footer_players, list):
        footer_players = [footer_players]

    name_to_slot = {name: slot for slot, name in players.items()}
    winner_team = None

    for p in footer_players:
        if not isinstance(p, dict):
            continue

        name = p.get('2')
        player_result = p.get('4')  # 1 = win, 2 = loss typically
        team = p.get('5')

        if not name:
            continue

        slot = name_to_slot.get(name)
        slot_key = str(slot) if slot else None

        if player_result == 1:  # Win
            result['winners'].append(name)
            if slot_key:
                result['player_results'][slot_key] = 'win'
            if team:
                winner_team = team
        elif player_result == 2:  # Loss
            result['losers'].append(name)
            if slot_key:
                result['player_results'][slot_key] = 'loss'

    if result['winners']:
        result['result'] = 'complete'
        result['winner_team'] = winner_team

    return result


def extract_player_teams(footer: Optional[dict], players: dict) -> dict:
    """Extract team assignment for each player from footer.

    Returns dict mapping player_id (int) to team number (int).
    """
    name_to_team = {}
    if footer and '3' in footer:
        for p in footer['3']:
            if not isinstance(p, dict):
                print(f"[DEBUG] Unexpected non-dict in footer['3']: {type(p).__name__} = {repr(p)}")
                continue
            name = p.get('2')
            team = p.get('5')
            if name and team:
                name_to_team[name] = team

    # Map player_id to team using players dict
    player_teams = {}
    for pid, name in players.items():
        team = name_to_team.get(name)
        if team:
            player_teams[pid] = team

    return player_teams
