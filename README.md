# Stormgate Replay Parser

A Python tool for parsing Stormgate (.SGReplay) replay files. Extracts player information, game details, actions, chat messages, and APM statistics.

## Features

- Parse Stormgate replay files (.SGReplay)
- Extract map name, game duration, and player information
- Analyze player actions and calculate APM (Actions Per Minute)
- Export all actions to JSON for further analysis
- Support for batch processing multiple replays

## Installation

1. Clone this repository:
```bash
git clone https://github.com/yourusername/stormgate-replay-parser.git
cd stormgate-replay-parser
```

2. Install dependencies:
```bash
pip install bbpb
```

## Usage

### Basic Analysis

```bash
python parse_sgreplay.py path/to/replay.SGReplay
```

Example output:
```
=== Stormgate Replay Analysis ===

Game Info:
  Map: DesolateTemple
  Duration: 13:28
  Changelist: 107125

Players:
  1. PlayerOne
  2. PlayerTwo

Actions by Player:
  PlayerOne: 2,876 actions (213.4 APM)
  PlayerTwo: 3,012 actions (223.5 APM)
```

### Export Actions to JSON

```bash
python parse_sgreplay.py replay.SGReplay --json
```

This creates `replay_actions.json` with all parsed actions.

### Quiet Mode (JSON only, no console output)

```bash
python parse_sgreplay.py replay.SGReplay --json --quiet
```

### Custom Output Path

```bash
python parse_sgreplay.py replay.SGReplay --json --output custom_output.json
```

## Replay Format

See [SGREPLAY_FORMAT.md](SGREPLAY_FORMAT.md) for detailed documentation of the replay file format.

Key points:
- Stormgate replays are **command-based** (similar to StarCraft 2)
- They record player inputs/commands, not game state
- Player resources are NOT stored (must be simulated)
- Unit positions are NOT continuously tracked

## Limitations

- **No resource tracking**: Player resources must be simulated from build commands
- **No unit positions**: Only target entity IDs are recorded, not coordinates
- **Hash-based IDs**: Entity and ability types use hashed identifiers

## File Structure

```
.
├── parse_sgreplay.py     # Main parser script
├── SGREPLAY_FORMAT.md    # Replay format documentation
├── README.md             # This file
└── .gitignore
```

## License

MIT License
