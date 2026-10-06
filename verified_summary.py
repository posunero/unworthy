"""Adapt verified records to the existing dashboard without legacy heuristics."""
from collections import Counter, defaultdict
from pathlib import Path


def dashboard_summary(decoded, filepath):
    events = decoded['events']
    players = {e['clientId']: e['clientName'] for e in events if e.get('clientName')}
    actions, chat = [], []
    buildings, upgrades, production = defaultdict(list), defaultdict(list), defaultdict(list)
    rewards = defaultdict(list)
    factions = {pid: 'Unknown' for pid in players}
    result = {'result': 'unknown', 'winners': [], 'losers': [], 'player_results': {}}
    teams = {}
    # Footer playerNumber and router clientID are different namespaces. Match
    # names only when unique on both sides; otherwise leave attribution unknown.
    footer_players = decoded['footer']['players']
    name_counts = Counter(player['displayName'] for player in footer_players)
    client_counts = Counter(players.values())
    for player in footer_players:
        name = player['displayName']
        if name_counts[name] != 1 or client_counts[name] != 1:
            continue
        pid = next(pid for pid, value in players.items() if value == name)
        teams[pid] = player['team']
        outcome = player['endOfGameResult']
        if outcome in ('EndOfGameResult_WIN', 'EndOfGameResult_FORCE_WIN'):
            result['winners'].append(name)
            result['player_results'][str(pid)] = 'win'
        elif outcome in ('EndOfGameResult_LOSS', 'EndOfGameResult_FORCE_LOSS'):
            result['losers'].append(name)
            result['player_results'][str(pid)] = 'loss'
        elif outcome in ('EndOfGameResult_TIE', 'EndOfGameResult_FORCE_TIE'):
            result['player_results'][str(pid)] = 'tie'
    if players and len(result['player_results']) == len(players):
        result['result'] = 'complete'
    for e in events:
        pid, ticks = e['clientId'], e['timestampTicks']
        seconds = ticks // 1024
        time = f'{seconds // 60:02}:{seconds % 60:02}'
        action = {'frame': ticks, 'time': time, 'player_id': pid,
                  'player': players.get(pid, f'Client {pid}'),
                  'type': 'COMMAND' if e['category'] == 'gameplay_command' else e['category'].upper(),
                  'description': e['description'], 'raw': e['decoded'],
                  'category': e['category'], 'queued': e.get('queued', False),
                  'selection_entity_ids': e.get('selectionEntityIds'),
                  'command_type': e.get('commandType'), 'action_type': e['actionType']}
        if 'positionWorld' in e:
            action.update(e['positionWorld'])
        ability = e.get('abilityCommand')
        if ability:
            action.update(ability_id=ability['archetypeId'], ability_name=ability['name'],
                          command_index=ability['commandIndex'])
        actions.append(action)
        if e['actionType'] == 'chat':
            chat.append({'frame': ticks, 'time': time, 'player': action['player'],
                         'text': e['decoded']['chat']['text']})
        if not ability or action['type'] != 'COMMAND':
            continue
        # This is explicitly an inference, not the numeric footer faction enum.
        name = ability['name']
        for faction, markers in {'Vanguard': ('Barracks', 'HQSpawn', 'WorkerConstruct'),
                                 'Infernal': ('Imp_', 'Shrine_', 'IronVault', 'Hellforge'),
                                 'Celestial': ('Arcship', 'Celestial_', 'CreationChamber')}.items():
            if any(marker in name for marker in markers):
                factions[pid] = faction
        if not e.get('abilityExecutionRequested', False):
            continue
        command = ability.get('command', {})
        request = {'frame': ticks, 'time': time, 'status': 'requested',
                   'ability_id': ability['archetypeId'], 'command_index': ability['commandIndex']}
        target = command.get('unit')
        if name.startswith('StormgateAbilityCreate'):
            rewards[pid].append(dict(request, reward_id=ability['archetypeId'],
                                     reward_name=name.removeprefix('StormgateAbilityCreate')))
        if ability['baseType'] == 'ConstructAbilityData' and target and target != 'emptyRef':
            buildings[pid].append(dict(request, building_name=target, building_type=None,
                                       **e.get('positionWorld', {})))
        elif ability['baseType'] == 'SpawnAbilityData' and target and target != 'emptyRef':
            production[pid].append(dict(request, building=name, unit_name=target))
        elif ability['baseType'] == 'ResearchAbilityData' and command.get('upgrade') not in (None, 'emptyRef'):
            upgrades[pid].append(dict(request, upgrade_id=None, upgrade_name=command['upgrade']))
    return {
        'file': Path(filepath).name, 'header': decoded['header'], 'map': decoded['footer']['mapName'],
        'players': players, 'player_teams': teams, 'player_factions': factions,
        'faction_source': 'inferred from resolved ability names', 'game_result': result,
        'building_orders': dict(buildings), 'player_upgrades': dict(upgrades),
        'stormgate_rewards': dict(rewards), 'unit_production_timeline': dict(production),
        'unit_production': {pid: dict(Counter(p['building'] for p in items)) for pid, items in production.items()},
        'duration_seconds': decoded['footer']['maxSimTime'] / 1024,
        'total_messages': len(events), 'total_actions': len(actions),
        'raw_size_bytes': decoded['coverage']['decompressedBytesConsumed'],
        'action_types': dict(Counter(a['type'] for a in actions)), 'actions': actions, 'chat': chat,
        'target_type_stats': {}, 'ability_stats': dict(Counter(a['ability_name'] for a in actions if a['type'] == 'COMMAND' and 'ability_name' in a)),
        'entities': {}, 'footer': decoded['footer'], 'coverage': decoded['coverage'],
        'parser_mode': 'verified-107842', 'catalog_matched': decoded['catalogMatched'],
        'analysis_note': 'Commands and build/train/research requests are recorded intent, not successful outcomes. Factions are inferred. Timeline uses recording time.' + ('' if decoded['catalogMatched'] else ' No matching map catalog: ability meanings remain unresolved.'),
    }
