"""Tests for replay analysis functions."""

import pytest
from replay_analyzers import (
    frame_to_time,
    frame_to_seconds,
    extract_player_upgrades,
    extract_stormgate_rewards,
    extract_game_result,
    extract_player_teams,
    FRAME_RATE_HZ,
)


class TestFrameConversion:
    """Tests for frame conversion functions."""

    def test_frame_to_time_zero(self):
        """Test zero frames."""
        assert frame_to_time(0) == "00:00"

    def test_frame_to_time_one_minute(self):
        """Test one minute worth of frames."""
        frames = 60 * FRAME_RATE_HZ  # 60 seconds
        assert frame_to_time(frames) == "01:00"

    def test_frame_to_time_mixed(self):
        """Test mixed minutes and seconds."""
        frames = (2 * 60 + 30) * FRAME_RATE_HZ  # 2:30
        assert frame_to_time(frames) == "02:30"

    def test_frame_to_time_none(self):
        """Test None input."""
        assert frame_to_time(None) == "00:00"

    def test_frame_to_seconds_zero(self):
        """Test zero frames to seconds."""
        assert frame_to_seconds(0) == 0.0

    def test_frame_to_seconds_one_second(self):
        """Test one second worth of frames."""
        assert frame_to_seconds(FRAME_RATE_HZ) == 1.0

    def test_frame_to_seconds_none(self):
        """Test None input."""
        assert frame_to_seconds(None) == 0


class TestExtractPlayerUpgrades:
    """Tests for extract_player_upgrades function."""

    def test_empty_actions(self):
        """Test with no actions."""
        result = extract_player_upgrades([])
        assert result == {}

    def test_non_command_actions_ignored(self):
        """Test that non-COMMAND actions are ignored."""
        actions = [
            {'type': 'SYNC', 'player_id': 1, 'ability_name': 'MorphToHQTier2'},
        ]
        result = extract_player_upgrades(actions)
        assert result == {}

    def test_upgrade_extracted(self):
        """Test upgrade extraction."""
        actions = [
            {
                'type': 'COMMAND',
                'player_id': 1,
                'ability_name': 'MorphToHQTier2',
                'ability_id': 12345,
                'frame': 1000,
                'time': '00:01',
            },
        ]
        result = extract_player_upgrades(actions)
        assert 1 in result
        assert len(result[1]) == 1
        assert result[1][0]['upgrade_name'] == 'Upgrade to HQ Tier 2'

    def test_stormgate_abilities_excluded(self):
        """Test that Stormgate abilities are not treated as upgrades."""
        actions = [
            {
                'type': 'COMMAND',
                'player_id': 1,
                'ability_name': 'StormgateAbilityCreateTier1Healer',
                'ability_id': 12345,
                'frame': 1000,
                'time': '00:01',
            },
        ]
        result = extract_player_upgrades(actions)
        assert result == {}

    def test_deduplication(self):
        """Test that duplicate upgrades are not counted twice."""
        actions = [
            {
                'type': 'COMMAND',
                'player_id': 1,
                'ability_name': 'MorphToHQTier2',
                'ability_id': 12345,
                'frame': 1000,
                'time': '00:01',
            },
            {
                'type': 'COMMAND',
                'player_id': 1,
                'ability_name': 'MorphToHQTier2',
                'ability_id': 12345,
                'frame': 2000,
                'time': '00:02',
            },
        ]
        result = extract_player_upgrades(actions)
        assert len(result[1]) == 1


class TestExtractStormgateRewards:
    """Tests for extract_stormgate_rewards function."""

    def test_empty_actions(self):
        """Test with no actions."""
        result = extract_stormgate_rewards([])
        assert result == {}

    def test_reward_extracted(self):
        """Test reward extraction."""
        actions = [
            {
                'type': 'COMMAND',
                'player_id': 1,
                'ability_name': 'StormgateAbilityCreateTier1Healer',
                'ability_id': 12345,
                'frame': 1000,
                'time': '00:01',
            },
        ]
        result = extract_stormgate_rewards(actions)
        assert 1 in result
        assert len(result[1]) == 1
        assert result[1][0]['reward_name'] == 'Tier 1: Healer'

    def test_non_stormgate_abilities_excluded(self):
        """Test that regular abilities are excluded."""
        actions = [
            {
                'type': 'COMMAND',
                'player_id': 1,
                'ability_name': 'MorphToHQTier2',
                'ability_id': 12345,
                'frame': 1000,
                'time': '00:01',
            },
        ]
        result = extract_stormgate_rewards(actions)
        assert result == {}


class TestExtractGameResult:
    """Tests for extract_game_result function."""

    def test_no_footer(self):
        """Test with no footer."""
        result = extract_game_result(None, {})
        assert result['result'] == 'unknown'
        assert result['winners'] == []
        assert result['losers'] == []

    def test_complete_game(self):
        """Test complete game extraction."""
        footer = {
            '3': [
                {'2': 'Alice', '4': 1, '5': 1},  # Win, team 1
                {'2': 'Bob', '4': 2, '5': 2},    # Loss, team 2
            ]
        }
        players = {1: 'Alice', 2: 'Bob'}
        result = extract_game_result(footer, players)

        assert result['result'] == 'complete'
        assert 'Alice' in result['winners']
        assert 'Bob' in result['losers']
        assert result['player_results']['1'] == 'win'
        assert result['player_results']['2'] == 'loss'

    def test_non_dict_entries_skipped(self):
        """Test that non-dict entries in footer are skipped."""
        footer = {
            '3': [
                'invalid_string_entry',
                {'2': 'Alice', '4': 1, '5': 1},
            ]
        }
        players = {1: 'Alice'}
        result = extract_game_result(footer, players)
        assert 'Alice' in result['winners']


class TestExtractPlayerTeams:
    """Tests for extract_player_teams function."""

    def test_no_footer(self):
        """Test with no footer."""
        result = extract_player_teams(None, {})
        assert result == {}

    def test_teams_extracted(self):
        """Test team extraction."""
        footer = {
            '3': [
                {'2': 'Alice', '5': 1},
                {'2': 'Bob', '5': 1},
                {'2': 'Charlie', '5': 2},
                {'2': 'Dave', '5': 2},
            ]
        }
        players = {1: 'Alice', 2: 'Bob', 3: 'Charlie', 4: 'Dave'}
        result = extract_player_teams(footer, players)

        assert result[1] == 1
        assert result[2] == 1
        assert result[3] == 2
        assert result[4] == 2

    def test_non_dict_entries_skipped(self):
        """Test that non-dict entries are skipped."""
        footer = {
            '3': [
                'invalid_string_entry',
                {'2': 'Alice', '5': 1},
            ]
        }
        players = {1: 'Alice'}
        result = extract_player_teams(footer, players)
        assert result[1] == 1
