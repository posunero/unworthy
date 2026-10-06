"""Source-derived dispatch regressions and integrity of the bounded inventory."""
import gzip
import json
from pathlib import Path
import sys

import pytest

from recovered_replay import (
    CATALOG, SEMANTICS, SelectionTracker, catalog_for_hash, load_catalog,
    load_catalog_corpus, message_classes, native_participant_dispatch,
)
from verified_summary import dashboard_summary
from tests.test_verified_pipeline import fixture_bytes, parse_fixture


@pytest.mark.parametrize('queued,smart,expected', [
    (False, False, 2472102578), (True, False, 3322138414),
    (False, True, 2626128676), (True, True, 307192056),
])
def test_native_selection_order_flag_dispatch(queued, smart, expected):
    payload = {'orderType': 12, 'targetEntityId': 42, 'targetEntityKind': 99,
               'position': {'x': -16384, 'y': 0}, 'selectionIndex': 1,
               'queued': queued, 'smart': smart, 'isAI': True}
    actual = native_participant_dispatch('selectionOrder', payload)
    assert actual['verb'] == expected
    assert (actual['data'], actual['subject'], actual['kind']) == (12, 42, 99)
    assert actual['position']['x'] == -16384
    assert actual['selectionIndex'] == 1
    assert not actual['isAIUsedByThisBridge']


@pytest.mark.parametrize('field,bit', [
    ('currentlyActive', 1), ('buildWorkers', 2), ('maintainSupply', 4),
    ('buildStructures', 8), ('buildArmy', 16), ('buildExpansion', 32),
])
def test_bot_options_match_native_bit_packing(field, bit):
    dispatch = native_participant_dispatch('setBotOptions', {field: True})
    assert dispatch == {'verb': 3926104316, 'data': bit}


def test_rejected_control_group_does_not_change_requested_state():
    tracker = SelectionTracker()
    assert tracker.apply(1, 'setControlGroup', {'controlGroupIndex': 10, 'entityId': [4]})['controlGroupIndexAccepted']
    rejected = tracker.apply(1, 'setControlGroup', {'controlGroupIndex': 11, 'entityId': [8]})
    assert not rejected['controlGroupIndexAccepted']
    assert (1, 11) not in tracker.control_groups
    assert tracker.control_groups[(1, 10)][0] == [4]


def test_all_explicit_map_selectors_have_reviewed_dispositions(tmp_path):
    _, _, NetAction = message_classes()
    definitions = json.loads(SEMANTICS.read_bytes())
    actions = []
    for value in definitions:
        action = NetAction()
        action.participantAction.mapAction.verb = int(value)
        actions.append(action)
    result = parse_fixture(tmp_path, fixture_bytes(actions))
    assert len(result['events']) == 66
    for event in result['events']:
        assert event['mapVerbRecognized']
        assert event['interpretationStatus'] == 'source_traced'
        assert event['mapVerbEvidence']['behavior']
        assert event['mapVerbEvidence']['evidence']
        assert event['runtimeRequirements']  # No invented outcome guarantee.


def test_ui_and_camera_payloads_are_not_ability_orders(tmp_path):
    _, _, NetAction = message_classes()
    ui, camera = NetAction(), NetAction()
    ui.participantAction.mapAction.verb = 3717677309
    ui.participantAction.mapAction.data = 335308633  # Same bits as HQSpawn, but UI String ID here.
    ui.participantAction.mapAction.kind = 123
    ui.participantAction.mapAction.subject = 2
    camera.participantAction.mapAction.verb = 417660425
    camera.participantAction.mapAction.subject = 90
    camera.participantAction.mapAction.kind = (-45) & 0xffffffff
    camera.participantAction.mapAction.data = 80
    result = parse_fixture(tmp_path, fixture_bytes([ui, camera]))
    assert 'abilityCommand' not in result['events'][0]
    assert result['events'][0]['interpretedPayload'] == {'commandStringId': 123, 'dataStringId': 335308633, 'player': 2}
    assert result['events'][1]['interpretedPayload'] == {'headingDegrees': 90, 'pitchDegrees': -45, 'zoomWorld': 80}


def test_autocast_change_is_not_a_training_request(tmp_path):
    _, _, NetAction = message_classes()
    action = NetAction()
    action.participantAction.mapAction.verb = 1102066046
    action.participantAction.mapAction.data = 335308633
    result = parse_fixture(tmp_path, fixture_bytes([action]))
    assert result['events'][0]['abilityCommand']['name'] == 'HQSpawn'
    assert not result['events'][0]['abilityExecutionRequested']
    assert dashboard_summary(result, 'synthetic')['unit_production_timeline'] == {}


def test_unknown_verb_remains_distinct_from_unknown_wire_fields(tmp_path):
    _, _, NetAction = message_classes()
    action = NetAction()
    action.participantAction.mapAction.verb = 0xdeadbeef
    result = parse_fixture(tmp_path, fixture_bytes([action]))
    assert result['coverage']['recordsWithUnknownFields'] == 0
    assert result['coverage']['unnamedMapActions'] == 1
    assert not result['events'][0]['mapVerbRecognized']


def test_all_shipped_catalogs_reconstruct_without_reference_leakage():
    corpus = load_catalog_corpus()
    assert len(corpus['maps']) == 98
    assert sum(m['definedAbilityCommandSlots'] for m in corpus['maps'].values()) == 91902
    for key, metadata in corpus['maps'].items():
        catalog = catalog_for_hash(key)
        assert catalog['mapRuntimeHash'] == key
        assert len(catalog['archetypes']) == metadata['archetypeCount']
        assert not set(metadata['removed']).intersection(catalog['archetypes'])
        assert catalog['wasmSha256'] == metadata['wasmSha256']
    assert catalog_for_hash('unknown-future-map') is None


def test_inventory_covers_both_entrypoints_and_preserves_limits():
    audit = json.loads(gzip.decompress(CATALOG.with_name('source-action-audit.json.gz').read_bytes()))
    definitions = json.loads(SEMANTICS.read_bytes())
    assert audit['sourceModuleCount'] == 98
    assert audit['cWatSelectorAgreement']
    assert audit['normalizedExportedEntrypointImplementations'] == 1
    assert not audit['fullSemanticRecovery']
    union = set()
    for module in audit['modules']:
        assert len(module['entrypoints']) == 2
        for entry in module['entrypoints']:
            assert entry['watSelectorsVerified']
            union.update(map(str, entry['selectors']))
    assert union == set(definitions)
    assert '4279446118' in union


def test_catalog_base_digest_survives_git_line_ending_conversion(tmp_path, monkeypatch):
    import recovered_replay
    original = CATALOG.read_text(encoding='utf-8')
    replacement = tmp_path / CATALOG.name
    monkeypatch.setattr(recovered_replay, 'CATALOG', replacement)
    try:
        for newline in ('\n', '\r\n'):
            replacement.write_bytes(original.replace('\n', newline).encode())
            load_catalog.cache_clear()
            load_catalog_corpus.cache_clear()
            assert len(load_catalog_corpus()['maps']) == 98
    finally:
        load_catalog.cache_clear()
        load_catalog_corpus.cache_clear()


def test_selector_tracer_handles_alias_before_first_signed_split():
    sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
    from recover_action_surface import selector_path
    source = '''var_l5 = var_i0;
var_i1 = 3000000000u;
var_i0 = (u32)((s32)var_i0 > (s32)var_i1);
if (var_i0) {goto var_B1;}
left_handler(instance);
goto var_B0;
var_B1:;
right_handler(instance);
var_B0:;
return var_i0;'''
    assert 'left_handler' in selector_path(source, 2500000000, 'var_l5')['entryBlock']
    assert 'right_handler' in selector_path(source, 7, 'var_l5')['entryBlock']
