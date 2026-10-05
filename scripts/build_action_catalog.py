"""Rebuild the compact map catalog from locally extracted game files.

Usage: python scripts/build_action_catalog.py --content PATH --module PATH --output PATH
No replay data is read or included in this catalog.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re


def fnv1a(text):
    value = 2166136261
    for byte in text.encode('utf-8'):
        value = ((value ^ byte) * 16777619) & 0xffffffff
    return value


def build(content, module):
    map_dir = content / 'PublishedMaps' / 'AshenBoneyard'
    runtime = map_dir / 'runtime_session.json'
    raw = json.loads(runtime.read_bytes())
    archetypes = {}
    for key, entry in raw['archetypes'].items():
        info = entry[1]
        archetypes[key] = {k: info[k] for k in ('id', '__base_type') if k in info}
        # Keep command references, not graphics, costs, or the full game data.
        commands = info.get('commands')
        if isinstance(commands, list):
            archetypes[key]['commands'] = [
                {k: v for k, v in command.items()
                 if k in ('id', 'unit', 'upgrade', 'button', 'entity', 'ability', 'morph_to')}
                for command in commands]
    rows = list(csv.DictReader((module / 'function-index.csv').open(encoding='utf-8')))
    rows.sort(key=lambda row: int(row['c_line']))
    i = next(i for i, row in enumerate(rows) if row['retained_debug_name'].startswith('on_action_shared('))
    lines = (module / 'main.c').read_text(encoding='utf-8').splitlines()
    start, end = int(rows[i]['c_line']) - 1, int(rows[i+1]['c_line']) - 1
    dispatch = '\n'.join(lines[start:end])
    pattern = r'var_i0 = var_p1;\s+var_i1 = (\d+)u;\s+var_i0 = var_i0 (?:==|!=) var_i1;'
    verbs = {m[1]: {'dispatchLine': start + dispatch[:m.start()].count('\n') + 1,
                    'status': 'recognized_handler', 'name': None}
             for m in re.finditer(pattern, dispatch)}
    sdk = content / 'data/tasks/public'
    for path in sorted(sdk.rglob('*.h')):
        text = path.read_text(encoding='utf-8-sig')
        for match in re.finditer(r'"([^"\n]+)"_n', text):
            key = str(fnv1a(match[1]))
            if key in verbs:
                verbs[key].update(name=match[1], status='named_in_sdk',
                                  source=str(path.relative_to(content)).replace('\\', '/'),
                                  sourceLine=text[:match.start()].count('\n')+1)
    # Names below describe observed handler behavior; they are not invented
    # original symbols. Provenance is recorded independently of the label.
    behavior = {
        '81781465': ('quick_macro', 'gameplay_command', 'QuickMacro::execute(unsigned int, Action)'),
        '1304751467': ('quick_macro_smart', 'gameplay_command', 'QuickMacro::execute_smart(unsigned int, Action)'),
        '3717677309': ('ui_event', 'ui_event', 'Events::UIEvent::broadcast(String, String, unsigned int)'),
        '429833619': ('player_chat_notification', 'notification', 'Events::PlayerChatMessageEvent::broadcast(unsigned int, String)'),
        '3703223256': ('cancel_production_queue_item', 'gameplay_command', 'ProductionQueueTask::on_action(Action const&); data selects cancel item'),
        '2472102578': ('command', 'gameplay_command', 'on_action_shared; selection handler and order queue dispatch'),
        '1432744753': ('command_ai', 'gameplay_command', 'on_action_shared; CommandAI diagnostic and selected-entity dispatch'),
        '580466764': ('update_selection', 'selection', 'PlayerTask::update_selection(unsigned int)'),
        '603245548': ('evaluate_win_condition', 'system', 'GameWorld::evaluate_active_win_condition()'),
        '1037210847': ('cache_save', 'system', 'GameWorld::cache_save()'),
        '1383849896': ('skip_cinematic', 'ui_event', 'Events::SkipCinematic::broadcast(unsigned int)'),
        '1911537387': ('create_player', 'system', 'Player::create(unsigned int)'),
    }
    for key, (name, category, handler) in behavior.items():
        verbs[key].update(name=name, category=category, handler=handler, status='handler_verified')
    for verb in verbs.values():
        if (verb['name'] or '').startswith('targeting_'):
            verb.update(category='targeting', handler='Events::TargetingStateChangedEvent::broadcast')
    return {
        'build': 107842, 'map': 'AshenBoneyard',
        'mapRuntimeHash': json.loads((map_dir / '_checksum.json').read_bytes())['runtime_hash'],
        'runtimeSessionSha256': hashlib.sha256(runtime.read_bytes()).hexdigest(),
        'wasmSha256': hashlib.sha256((map_dir / 'main.wasm').read_bytes()).hexdigest(),
        'coordinateScale': 16384, 'maxCommandIndexExclusive': 30,
        'provenance': {
            'dispatch': rows[i]['retained_debug_name'], 'dispatchWatLine': int(rows[i]['wat_line']),
            'abilityEncoding': 'order.h: AbilityOrderCommand::get_order_data; hash + command_index',
            'abilityDecoding': 'AbilityOrderCommand::from_order_data; first archetype found at offsets 0..29',
            'coordinates': 'snowplay/types.h: Distance = Q<i32, 16 * 1024, 1, 0, 0>',
            'scope': 'All explicit verb comparisons in this map dispatcher; custom scripts may define additional verbs.'},
        'mapVerbs': dict(sorted(verbs.items(), key=lambda item: int(item[0]))),
        'archetypes': archetypes,
    }


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--content', required=True, type=Path)
    cli.add_argument('--module', required=True, type=Path)
    cli.add_argument('--output', required=True, type=Path)
    args = cli.parse_args()
    result = build(args.content, args.module)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(f"{len(result['mapVerbs'])} map verbs; {len(result['archetypes'])} archetypes")
