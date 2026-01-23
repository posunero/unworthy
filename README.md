# Stormgate Replay Parser

A Python tool for parsing Stormgate (.SGReplay) replay files with a web-based stats dashboard. Extracts player information, game details, actions, build orders, and provides comprehensive statistics.

## Features

- **Web Dashboard** - Interactive stats viewer with charts and filtering
- **Player Statistics** - Win rates, matchup analysis, race stats
- **All Players Mode** - Aggregate stats across all players in your replays
- **Build Order Tracking** - Opening buildings, sequences, and timing
- **Stormgate Rewards** - Track first reward choices and win rates
- **APM Analysis** - Actions per minute with timeline charts
- **Replay Parsing** - Full action timeline, chat logs, unit production

## Installation

1. Clone this repository
2. Install dependencies with uv:
```bash
uv sync
```

Or with pip:
```bash
pip install -r requirements.txt
```

## Web Dashboard

The easiest way to use the parser is through the web dashboard:

```bash
uv run python web/server.py
```

This starts a local server at http://localhost:8080 and opens your browser.

### Summary View

The default view shows aggregate statistics:

- **Player Stats** - Games played, wins, losses, win rate
- **Race Statistics** - Pick rates and win rates by faction
- **Matchup Analysis** - Performance against each enemy race
- **Opening Buildings** - Most common first buildings by matchup
- **Opening Sequences** - Common build order patterns
- **Stormgate Rewards** - First reward choice statistics
- **Map Statistics** - Win rates by map
- **Game Length** - Average duration for wins vs losses

### All Players Mode

Click the "All Players" button to see aggregate stats across all players in your replays:

- Race popularity across all games
- Most common openings by race
- Top players by games played
- Map and patch usage statistics

### Single Replay View

Switch to "Single Replay" to analyze individual games:

- Game overview (map, duration, winner)
- Player details with APM and faction
- APM over time chart
- Production timeline
- Building orders for each player
- Upgrades and research
- Unit production summary
- Chat log
- Full action timeline with filtering

### Filtering

- **Directory** - Select which replay folder to analyze
- **Player** - Focus on a specific player's stats
- **Patch** - Filter by game version (changelist)

## Command Line Usage

### Basic Analysis

```bash
uv run python parse_sgreplay.py path/to/replay.SGReplay
```

Example output:
```
=== Stormgate Replay Analysis ===

Game Info:
  Map: DesolateTemple
  Duration: 13:28
  Changelist: 107125

Players:
  1. PlayerOne (Vanguard) - Victory
  2. PlayerTwo (Infernal) - Defeat

Actions by Player:
  PlayerOne: 2,876 actions (213.4 APM)
  PlayerTwo: 3,012 actions (223.5 APM)
```

### Export to JSON

```bash
uv run python parse_sgreplay.py replay.SGReplay --json
```

Creates `replay_actions.json` with all parsed data.

### Quiet Mode

```bash
uv run python parse_sgreplay.py replay.SGReplay --json --quiet
```

### Custom Output Path

```bash
uv run python parse_sgreplay.py replay.SGReplay --json --output custom_output.json
```

## Replay Locations

The parser automatically looks for replays in:

- **Windows**: `%LOCALAPPDATA%\Stormgate\Saved\Replays`
- **Project folder**: `./replays/`

## Replay Format

See [SGREPLAY_FORMAT.md](SGREPLAY_FORMAT.md) for detailed documentation of the replay file format.

Key points:
- Stormgate replays are **command-based** (similar to StarCraft 2)
- They record player inputs/commands, not game state
- Player resources are NOT stored (must be simulated)
- Unit positions are NOT continuously tracked

## Limitations

- **No resource tracking**: Player resources must be simulated from build commands
- **No unit positions**: Only target coordinates for move/attack commands
- **Hash-based IDs**: Some entity and ability types use hashed identifiers

## File Structure

```
.
├── parse_sgreplay.py     # Main parser module
├── protobuf.py           # Protobuf decoding utilities
├── web/
│   ├── server.py         # Web server for stats dashboard
│   └── index.html        # Dashboard UI
├── assets/
│   └── runtime_session.json  # Game data mappings
├── SGREPLAY_FORMAT.md    # Replay format documentation
└── README.md             # This file
```

## Building Executable

To build a standalone Windows executable:

```bash
uv run pyinstaller --onefile \
  --add-data "web;web" \
  --add-data "assets;assets" \
  --name "sgreplay_parser" \
  parse_sgreplay.py
```

The executable will be in `dist/sgreplay_parser.exe`.

## License

MIT License
