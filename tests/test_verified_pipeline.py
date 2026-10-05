"""Binary-to-timeline checks using generated public fixtures, not personal replays."""
import gzip
import struct

import pytest

from recovered_replay import export_recovered, load_catalog, message_classes, resolve_order
from verified_summary import dashboard_summary


def encode_varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def fixture_bytes(actions, *, map_hash=None):
    Record, Footer, _ = message_classes()
    footer = Footer(mapName='AshenBoneyard', maxSimTime=2048,
                    mapRuntimeHash=map_hash or load_catalog()['mapRuntimeHash'])
    footer.players.add(playerNumber=1, displayName='Example', team=0, factionType=2)
    records = []
    for action in actions:
        record = Record(timeStamp=1024, clientID=1)
        record.netaction.bytes = action.SerializeToString()
        wire = record.SerializeToString()
        records.append(encode_varint(len(wire)) + wire)
    tail = footer.SerializeToString()
    return struct.pack('<5I', 0xE3B0A49D, 2, 20, 107842, len(tail)) + gzip.compress(b''.join(records)) + tail


def parse_fixture(tmp_path, wire):
    path = tmp_path / 'synthetic.SGReplay'
    path.write_bytes(wire)
    return export_recovered(path)


@pytest.mark.parametrize('kind', [f.name for f in message_classes()[2].DESCRIPTOR.fields])
def test_every_network_action_including_empty_messages(tmp_path, kind):
    _, _, NetAction = message_classes()
    action = NetAction()
    getattr(action, kind).SetInParent()
    result = parse_fixture(tmp_path, fixture_bytes([action]))
    assert result['coverage']['records'] == 1
    assert result['events'][0]['actionType'] == kind
    assert result['coverage']['recordsWithUnknownFields'] == 0


def test_commands_resolve_without_counting_targeting_as_production(tmp_path):
    _, _, NetAction = message_classes()
    selection, order, targeting, macro = [NetAction() for _ in range(4)]
    selection.participantAction.participantId = 7
    selection.participantAction.setSelection.entityId.extend([42, 43])
    order.participantAction.participantId = 7
    command = order.participantAction.selectionOrder
    command.orderType = 2118496581  # Imp_Construct + 2: Iron Vault
    command.position.x, command.position.y = -16384, 32768
    command.queued = True
    targeting.participantAction.mapAction.verb = 2402589206
    targeting.participantAction.mapAction.data = 335308633  # HQSpawn: Worker
    macro.participantAction.mapAction.verb = 81781465
    macro.participantAction.mapAction.data = 335308633
    result = parse_fixture(tmp_path, fixture_bytes([selection, order, targeting, macro]))
    event = result['events'][1]
    assert event['selectionEntityIds'] == [42, 43]
    assert event['positionWorld'] == {'x': -1.0, 'y': 2.0}
    assert event['queued']
    assert event['abilityCommand']['commandIndex'] == 2
    assert event['abilityCommand']['command']['unit'] == 'IronVault'
    summary = dashboard_summary(result, 'synthetic.SGReplay')
    assert sum(a['type'] == 'COMMAND' for a in summary['actions']) == 2
    assert len(summary['unit_production_timeline'][1]) == 1
    assert summary['game_result']['result'] == 'unknown'


def test_map_hash_mismatch_never_applies_ability_names(tmp_path):
    _, _, NetAction = message_classes()
    action = NetAction()
    action.participantAction.selectionOrder.orderType = 2118496581
    result = parse_fixture(tmp_path, fixture_bytes([action], map_hash='different-map'))
    assert not result['catalogMatched']
    assert 'abilityCommand' not in result['events'][0]


def test_unknown_nested_action_is_preserved_and_reported(tmp_path):
    _, _, NetAction = message_classes()
    action = NetAction()
    action.ParseFromString(bytes.fromhex('a00601'))
    result = parse_fixture(tmp_path, fixture_bytes([action]))
    assert result['coverage']['recordsWithUnknownFields'] == 1
    assert 'a00601' in result['events'][0]['rawHex']


@pytest.mark.parametrize('damage', ['crc', 'footer', 'truncated', 'build', 'junk'])
def test_corrupt_or_unsupported_container_rejected(tmp_path, damage):
    wire = bytearray(fixture_bytes([]))
    footer_length = struct.unpack_from('<I', wire, 16)[0]
    if damage == 'crc':
        wire[-footer_length-8] ^= 1
    elif damage == 'footer':
        struct.pack_into('<I', wire, 16, len(wire) + 1)
    elif damage == 'truncated':
        wire = wire[:25]
    elif damage == 'build':
        struct.pack_into('<I', wire, 12, 107841)
    else:
        wire[-footer_length:-footer_length] = b'junk'
    with pytest.raises(ValueError):
        parse_fixture(tmp_path, wire)


def test_order_resolution_matches_first_archetype_and_exclusive_bound():
    catalog = {'maxCommandIndexExclusive': 30, 'archetypes': {
        '100': {'id': 'First', '__base_type': 'AbilityData'},
        '101': {'id': 'Second', '__base_type': 'AbilityData'}}}
    assert resolve_order(102, catalog)['name'] == 'Second'
    assert resolve_order(130, catalog)['commandIndex'] == 29
    assert resolve_order(131, catalog) is None


def test_standard_parser_uses_verified_results(tmp_path):
    from parse_sgreplay import SGReplayParser
    _, _, NetAction = message_classes()
    action = NetAction()
    action.bootstrap.displayName.userName = 'Example'
    path = tmp_path / 'integration.SGReplay'
    path.write_bytes(fixture_bytes([action]))
    parser = SGReplayParser(str(path)).load().parse()
    result = parser.to_json(include_actions=True)
    assert result['parser_mode'] == 'verified-107842'
    assert result['player_teams'] == {1: 0}
    assert parser.get_game_result()['result'] == 'unknown'
    assert not result['game_result']['winners']
    assert not result['game_result']['losers']
    assert result['header']['footer_length'] > 0
    assert 'flags' not in result['header']


def test_stormgate_reward_is_preserved_as_request(tmp_path):
    _, _, NetAction = message_classes()
    action = NetAction()
    action.participantAction.selectionOrder.orderType = 2524872064
    result = dashboard_summary(parse_fixture(tmp_path, fixture_bytes([action])), 'synthetic.SGReplay')
    reward = result['stormgate_rewards'][1][0]
    assert reward['reward_name'] == 'Tier2Avatar'
    assert reward['status'] == 'requested'
