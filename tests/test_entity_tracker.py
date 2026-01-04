"""Tests for EntityTracker."""

import pytest
from entity_tracker import EntityTracker


class TestEntityTracker:
    """Tests for EntityTracker class."""

    def test_init(self):
        """Test EntityTracker initialization."""
        tracker = EntityTracker()
        assert tracker.entities == {}
        assert tracker.ability_lookup is None

    def test_record_action_creates_entity(self):
        """Test that recording an action creates entity entry."""
        tracker = EntityTracker()
        action = {
            'target_id': 12345,
            'frame': 1000,
            'time': '00:01',
            'player_id': 1,
        }
        tracker.record_action(action)

        assert 12345 in tracker.entities
        entity = tracker.entities[12345]
        assert entity['id'] == 12345
        assert entity['first_seen'] == 1000
        assert entity['action_count'] == 1
        assert 1 in entity['players']

    def test_record_action_updates_entity(self):
        """Test that subsequent actions update entity."""
        tracker = EntityTracker()
        action1 = {
            'target_id': 12345,
            'frame': 1000,
            'time': '00:01',
            'player_id': 1,
        }
        action2 = {
            'target_id': 12345,
            'frame': 2000,
            'time': '00:02',
            'player_id': 1,
        }
        tracker.record_action(action1)
        tracker.record_action(action2)

        entity = tracker.entities[12345]
        assert entity['first_seen'] == 1000
        assert entity['last_seen'] == 2000
        assert entity['action_count'] == 2

    def test_record_action_tracks_abilities(self):
        """Test that abilities are tracked."""
        tracker = EntityTracker()
        action = {
            'target_id': 12345,
            'frame': 1000,
            'time': '00:01',
            'player_id': 1,
            'ability_name': 'TestAbility',
            'ability_id': 100,
        }
        tracker.record_action(action)

        entity = tracker.entities[12345]
        assert 'TestAbility' in entity['abilities_cast']

    def test_record_action_ignores_invalid_target(self):
        """Test that invalid target_id is ignored."""
        tracker = EntityTracker()
        action = {'target_id': None, 'frame': 1000}
        tracker.record_action(action)
        assert len(tracker.entities) == 0

        action = {'frame': 1000}  # No target_id
        tracker.record_action(action)
        assert len(tracker.entities) == 0

    def test_infer_type_from_spawn(self):
        """Test entity type inference from spawn abilities."""
        tracker = EntityTracker()
        action = {
            'target_id': 12345,
            'frame': 1000,
            'time': '00:01',
            'player_id': 1,
            'target_type': 100,
            'target_type_name': 'BarracksSpawn',
        }
        tracker.record_action(action)

        entity = tracker.entities[12345]
        assert entity['inferred_type'] == 'Barracks'

    def test_infer_owners(self):
        """Test owner inference from player actions."""
        tracker = EntityTracker()
        # Player 1 uses entity 3 times
        for _ in range(3):
            tracker.record_action({
                'target_id': 12345,
                'frame': 1000,
                'time': '00:01',
                'player_id': 1,
            })
        # Player 2 uses entity 1 time
        tracker.record_action({
            'target_id': 12345,
            'frame': 2000,
            'time': '00:02',
            'player_id': 2,
        })

        players = {1: 'Alice', 2: 'Bob'}
        tracker.infer_owners(players)

        entity = tracker.entities[12345]
        assert entity['inferred_owner'] == 1
        assert entity['owner_name'] == 'Alice'

    def test_get_summary(self):
        """Test getting entity summary."""
        tracker = EntityTracker()
        tracker.record_action({
            'target_id': 12345,
            'frame': 1000,
            'time': '00:01',
            'player_id': 1,
        })

        players = {1: 'Alice'}
        tracker.infer_owners(players)
        summary = tracker.get_summary()

        assert len(summary) == 1
        assert summary[0]['target_id'] == 12345
        assert summary[0]['owner'] == 'Alice'

    def test_to_dict(self):
        """Test converting to dictionary."""
        tracker = EntityTracker()
        tracker.record_action({
            'target_id': 12345,
            'frame': 1000,
            'time': '00:01',
            'player_id': 1,
        })

        result = tracker.to_dict()
        assert '12345' in result
        assert result['12345']['target_id'] == 12345
        assert result['12345']['players'] == [1]
