"""Regression coverage for schema-based interpretations, independent of private replays."""
import pytest

pytest.importorskip('google.protobuf')
from recovered_replay import as_dict, has_unknown_fields, message_classes, SelectionTracker, varint


def test_footer_team_is_not_result():
    _, Footer, _ = message_classes()
    footer = Footer()
    # Player 2, team 1, faction 2, absent endOfGameResult.
    footer.ParseFromString(bytes.fromhex('1a06080218012002'))
    player = as_dict(footer)['players'][0]
    assert player['team'] == 1
    assert player['factionType'] == 2
    assert player['endOfGameResult'] == 'EndOfGameResult_UNDECIDED'


def test_packed_selection_ids_and_empty_selection():
    Record, _, NetAction = message_classes()
    record = Record()
    selection = NetAction().participantAction.setSelection
    selection.ParseFromString(bytes.fromhex('0a0401960100'))
    assert as_dict(selection)['entityId'] == [1, 150, 0]
    selection.Clear()
    assert as_dict(selection)['entityId'] == []


def test_order_targets_signed_coordinates_and_optional_false():
    Record, _, NetAction = message_classes()
    record = Record()
    order = NetAction().participantAction.selectionOrder
    order.targetEntityId = 42
    order.position.x = -65536
    order.queued = False
    decoded = as_dict(order)
    assert decoded['targetEntityId'] == 42
    assert decoded['position']['x'] == -65536
    assert decoded['queued'] is False
    assert 'smart' not in decoded


def test_selections_are_isolated_by_participant_and_index():
    tracker = SelectionTracker()
    tracker.apply(1, 'setSelection', {'entityId': [3, 4], 'selectionIndex': 2})
    tracker.apply(1, 'modifySelection', {'toRemoveEntityId': [3], 'toAddEntityId': [5], 'selectionIndex': 2})
    event = tracker.apply(1, 'selectionOrder', {'selectionIndex': 2})
    assert event['selectionEntityIds'] == [4, 5]
    assert event['selectionEstablishedByRecordedSet']
    assert not tracker.apply(2, 'selectionOrder', {'selectionIndex': 2})['selectionEstablishedByRecordedSet']
    assert not tracker.apply(1, 'selectionOrder', {})['selectionEstablishedByRecordedSet']
    tracker.apply(1, 'setSelection', {'entityId': [], 'selectionIndex': 2})
    assert tracker.apply(1, 'selectionOrder', {'selectionIndex': 2})['selectionEntityIds'] == []
    assert event['selectionEntityIds'] == [4, 5]  # earlier events remain snapshots


def test_unknown_fields_are_detected_recursively():
    Record, _, NetAction = message_classes()
    record = Record()
    record.ParseFromString(bytes.fromhex('a00601'))
    assert has_unknown_fields(record)
    record.DiscardUnknownFields()
    assert not has_unknown_fields(record)


@pytest.mark.parametrize('raw', [b'\x80', b'\xff' * 10, b'\x80' * 10 + b'\x00'])
def test_invalid_record_lengths_are_rejected(raw):
    with pytest.raises(ValueError):
        varint(raw, 0)


def test_real_replay_coverage_when_available():
    from pathlib import Path
    from recovered_replay import export_recovered
    path = Path(__file__).parents[1] / 'replays/CL107842-2026.10.04-12.13.SGReplay'
    if not path.exists():
        pytest.skip('Private reference replay not present')
    result = export_recovered(path)
    assert result['footer']['mapName'] == 'AshenBoneyard'
    assert result['coverage']['records'] == 1742
    assert result['coverage']['decompressedBytesConsumed'] == 59880
    assert result['coverage']['recordsWithUnknownFields'] == 0
    assert not result['footerHasUnknownFields']
    assert result['coverage']['actionTypes']['participantAction'] == 1516
