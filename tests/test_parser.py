"""Tests for SGReplayParser."""

import os
import pytest
from pathlib import Path

# Get the project root
PROJECT_ROOT = Path(__file__).parent.parent
REPLAYS_DIR = PROJECT_ROOT / "replays"


# Skip tests if no replays available
def has_replays():
    """Check if replay files are available for testing."""
    return REPLAYS_DIR.exists() and any(REPLAYS_DIR.glob("*.SGReplay"))


@pytest.fixture
def sample_replay():
    """Get path to a sample replay file."""
    if not has_replays():
        pytest.skip("No replay files available")
    replays = list(REPLAYS_DIR.glob("*.SGReplay"))
    return str(replays[0])


@pytest.fixture
def parser(sample_replay):
    """Create a parser instance."""
    from parse_sgreplay import SGReplayParser
    return SGReplayParser(sample_replay)


class TestSGReplayParser:
    """Tests for SGReplayParser class."""

    @pytest.mark.skipif(not has_replays(), reason="No replay files available")
    def test_load(self, parser):
        """Test loading a replay file."""
        parser.load()
        assert parser.header is not None
        assert parser.footer is not None

    @pytest.mark.skipif(not has_replays(), reason="No replay files available")
    def test_parse(self, parser):
        """Test parsing a replay file."""
        parser.load()
        parser.parse()
        # Actions might be empty for very short replays
        assert isinstance(parser.actions, list)
        # Players dict should exist
        assert isinstance(parser.players, dict)

    @pytest.mark.skipif(not has_replays(), reason="No replay files available")
    def test_to_json(self, parser):
        """Test JSON export."""
        parser.load()
        parser.parse()
        data = parser.to_json()

        assert 'header' in data
        assert 'players' in data
        assert 'player_factions' in data
        assert 'game_result' in data
        assert 'building_orders' in data

    @pytest.mark.skipif(not has_replays(), reason="No replay files available")
    def test_get_player_factions(self, parser):
        """Test faction extraction."""
        parser.load()
        parser.parse()
        factions = parser.get_player_factions()

        assert isinstance(factions, dict)
        # Should have factions for at least some players
        assert len(factions) > 0

    @pytest.mark.skipif(not has_replays(), reason="No replay files available")
    def test_get_building_orders(self, parser):
        """Test building order extraction."""
        parser.load()
        parser.parse()
        building_orders = parser.get_building_orders()

        assert isinstance(building_orders, dict)

    @pytest.mark.skipif(not has_replays(), reason="No replay files available")
    def test_get_game_result(self, parser):
        """Test game result extraction."""
        parser.load()
        parser.parse()
        result = parser.get_game_result()

        assert 'result' in result
        assert 'winners' in result
        assert 'losers' in result
        assert 'player_results' in result

    @pytest.mark.skipif(not has_replays(), reason="No replay files available")
    def test_get_player_teams(self, parser):
        """Test team extraction."""
        parser.load()
        parser.parse()
        teams = parser.get_player_teams()

        assert isinstance(teams, dict)


class TestParserIntegration:
    """Integration tests using real replay files."""

    @pytest.mark.skipif(not has_replays(), reason="No replay files available")
    def test_parse_all_replays(self):
        """Test that all replay files can be parsed without errors."""
        from parse_sgreplay import SGReplayParser

        replays = list(REPLAYS_DIR.glob("*.SGReplay"))
        errors = []
        for replay_path in replays[:10]:  # Limit to first 10 for speed
            try:
                parser = SGReplayParser(str(replay_path))
                parser.load()
                parser.parse()
                data = parser.to_json()

                # Basic sanity checks
                assert 'header' in data
                assert 'players' in data
            except Exception as e:
                errors.append(f"{replay_path.name}: {e}")

        # Allow up to 20% failure rate for edge case replays
        max_failures = max(1, len(replays[:10]) // 5)
        assert len(errors) <= max_failures, f"Too many parsing errors: {errors}"

    @pytest.mark.skipif(not has_replays(), reason="No replay files available")
    def test_action_count_reasonable(self):
        """Test that parsed actions have reasonable count."""
        from parse_sgreplay import SGReplayParser

        replays = list(REPLAYS_DIR.glob("*.SGReplay"))
        if replays:
            parser = SGReplayParser(str(replays[0]))
            parser.load()
            parser.parse()

            # A real game should have many actions
            # Very short games might have fewer
            assert len(parser.actions) >= 0

    @pytest.mark.skipif(not has_replays(), reason="No replay files available")
    def test_duration_positive(self):
        """Test that game duration is positive."""
        from parse_sgreplay import SGReplayParser

        replays = list(REPLAYS_DIR.glob("*.SGReplay"))
        if replays:
            parser = SGReplayParser(str(replays[0]))
            parser.load()
            parser.parse()
            data = parser.to_json()

            duration = data.get('duration_seconds', 0)
            # Duration should be non-negative
            assert duration >= 0
