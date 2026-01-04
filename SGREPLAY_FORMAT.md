# Stormgate Replay Format (.SGReplay)

Reverse-engineered documentation for Stormgate replay files.

## Overview

Stormgate replays use a **command-based format** (similar to StarCraft 2). They record player inputs/commands, not game state. This means:
- Player resources are NOT stored (must be simulated)
- Unit positions are NOT continuously tracked
- Only player commands/actions are recorded

## File Structure

### Header (20 bytes)

| Offset | Size | Type | Description |
|--------|------|------|-------------|
| 0x00 | 4 | uint32_le | Magic number: `0xE3B0A49D` |
| 0x04 | 4 | uint32_le | Version (typically 2) |
| 0x08 | 4 | uint32_le | Data offset (20) |
| 0x0C | 4 | uint32_le | Changelist number (e.g., 107125) |
| 0x10 | 4 | uint32_le | Flags |

### Compressed Data

After the 20-byte header:
- **Gzip header** (often 10 bytes, but can be longer if optional gzip header flags are set)
  - Magic: `1F 8B`
  - Compression method: `08` (deflate)
- **Deflate-compressed data**: Raw deflate stream (use zlib with `-MAX_WBITS`)

#### Important: bytes after the deflate stream (gzip trailer + extra footer)

Empirically (across the `.SGReplay` files in this repo), there are often bytes *after* the deflate stream
in the compressed payload:

- **Gzip trailer (8 bytes)**: CRC32 + ISIZE (RFC 1952)
- **Appended uncompressed protobuf footer (variable)**: a protobuf message containing metadata such as:
  - map name
  - player names
  - a long hex-ish match/game identifier string

This footer is not part of the decompressed length-prefixed message stream, so a parser must look at
`zlib.decompressobj().unused_data` to capture it.

#### Footer Structure

The footer protobuf contains game result information:

```protobuf
message Footer {
    optional uint32 final_frame = 1;     // Last game frame
    optional string map_name = 2;        // Map name
    repeated PlayerResult players = 3;   // Player results
    optional string match_id = 4;        // Match identifier (hex string)
}

message PlayerResult {
    optional uint32 slot = 1;            // Player slot (1-4)
    optional string name = 2;            // Player display name
    optional uint32 result = 3;          // 1 = loss, absent = win
    optional uint32 team = 4;            // Team number
    optional uint32 position = 5;        // Player position
}
```

**Game Result Detection:**
- If `PlayerResult.result = 1`, the player **lost**
- If `PlayerResult.result` is absent/missing, the player **won**
- Works for 1v1, 2v2, and other team formats

### Decompressed Content

The decompressed data is a stream of **length-prefixed Protocol Buffer messages**.

```
[varint: length][protobuf message][varint: length][protobuf message]...
```

## Message Structure

Each message follows this general structure:

```protobuf
message ReplayMessage {
    optional uint64 frame = 1;      // Timestamp in milliseconds
    optional uint32 player_id = 2;  // Player slot (1-4) or 64 for system
    optional Content content = 3;
}

message Content {
    optional ActionData data = 1;
}
```

### Frame/Timestamp

- Field 1 is the timestamp in **ticks at 1024 Hz** from game start (not milliseconds)
- To convert to seconds: `frame / 1024`
- To convert to mm:ss: `minutes = frame / 1024 / 60`, `seconds = (frame / 1024) % 60`

### Player ID

- Values 1-5: Player slots
- Value 64: System/global messages (game setup, spawns)

### Verified Map Name Location

Across the replays in this repository, the map name is present very early (often the first message)
at the path:

- `3 -> 1 -> 3 -> 2` (string)

Other paths may exist in other versions, but this one is confirmed for the files in this repo.
## Action Types (Field Numbers in ActionData)

| Field | Type | Description |
|-------|------|-------------|
| 1 | message | Map/game info (first message) |
| 3 | message | Game initialization |
| 4 | message | Unit/building spawn |
| 7 | message | **Player command** (most common) |
| 13 | message | Unknown (rare) |
| 15 | message | Player state/ready |
| 17 | message | Game state |
| 24 | message | Unknown (appears with commands) |
| 25 | message | Unknown |
| 31 | message | Unknown |
| 37 | message | Player join info |
| 40 | message | Sync/checksum data |
| 44 | message | ID mapping |
| 45 | message | Player profile/chat |
| 47 | message | Ping/signal |

## Field 7: Player Commands

This is the main action field, containing player inputs.

```protobuf
message Command {
    optional uint32 player_slot = 1;  // Which player (1-4)
    optional SubCommand sub = 2;      // Sub-command data
    optional Unknown3 unk3 = 3;
    optional AbilityData ability = 4; // Ability/action info
    optional TargetData target = 9;   // Target entity
    optional Unknown11 unk11 = 11;
    optional Unknown12 unk12 = 12;
    optional Unknown14 unk14 = 14;    // Appears in first commands
}
```

### Field 7 -> 9: Target Data

```protobuf
message TargetData {
    optional uint32 target_id = 1;    // Entity ID being targeted
    optional uint32 target_type = 2;  // Entity type hash/ID
    optional uint32 player_slot = 3;  // Player slot index (not player_id!)
    optional uint32 entity_ref = 4;   // Entity handle/selection reference
    optional int64 x_coord = 5;       // X coordinate (fixed-point ÷65536)
    optional int64 y_coord = 6;       // Y coordinate (fixed-point ÷65536)
}
```

#### Target Data Subfields

**Fields 3-4 (Player/Entity References):**
- Used in global UI actions (selection, control groups)
- Field 3 is a player slot index (differs from player_id)
- Field 4 contains entity handles, often appear in pairs

**Fields 5-6 (Coordinates):**
- Signed 64-bit fixed-point coordinates
- Divide by 65536 to get world position
- Used for positional commands: attack-move, build placement, ability targeting
- Example: `x=18446744073557508096` → signed: `-152043520` → world: `-2320.3`

**Subfield patterns by command type:**
| Pattern | Count | Usage |
|---------|-------|-------|
| No f3-f6 | ~3000 | Basic unit commands |
| f3 + f4 | ~800 | Global UI actions |
| f5 + f6 | ~500 | Positional commands (attack, build) |
| f3 + f5 + f6 | ~90 | UI + position |

### Field 7 -> 4: Ability Data

```protobuf
message AbilityData {
    optional uint32 ability_id = 1;   // Ability type hash
    optional uint32 position_index = 2; // Build position slot?
    optional uint32 building_type = 3;  // Building type ID (for construction)
    optional Coordinates coords = 4;    // Target coordinates
    optional uint32 unk5 = 5;
    optional uint32 unk6 = 6;
}

message Coordinates {
    optional int64 x = 1;  // Fixed-point, divide by 65536
    optional int64 y = 2;  // Fixed-point, divide by 65536
}
```

#### Build Structure Command (field 4 with fields 2, 3, 4)

When a worker builds a structure, the command contains:

```
field 4: {
  '2': position_index,    // Varies per building type
  '3': BUILDING_TYPE_ID,  // The structure being built (maps to runtime_session.json)
  '4': {                  // Coordinates
    '1': x_coord,         // Signed int64, divide by 65536 for world pos
    '2': y_coord
  },
  '5': 0,
  '6': 1
}
```

**Example - Build Barracks:**
```json
{
  "1": 1,
  "4": {
    "2": 786729,
    "3": 597044510,      // = Barracks (UnitData)
    "4": {"1": ..., "2": ...},
    "5": 0,
    "6": 1
  }
}
```

**Known Building Type IDs:**
| ID | Building | Base Type |
|----|----------|-----------|
| 597044510 | Barracks | UnitData |
| 1503114586 | MegaResourceA (Supply) | ResourceData |

**Known Spawn Ability IDs:**
| ID | Ability | Building |
|----|---------|----------|
| 749407741 | BarracksSpawn | Barracks |
| 335308633 | HQSpawn | HQ |
| 1485475066 | Shrine_Spawn | Shrine |
| 3191913349 | IronVault_Spawn | Iron Vault |
| 1954853105 | Arcship_Spawn | Arcship |
| 2548286134 | CreationChamber_Spawn | Creation Chamber |

#### Spawn Unit Command (field 4 with field 1)

When a production building spawns a unit:

```
field 4: {
  '1': SPAWN_ABILITY_ID,  // e.g., 749407741 = BarracksSpawn
  '4': '',                // Empty
  '5': 0,
  '6': 0
}
```

**Important limitation:** The spawn command only records the spawn ability, NOT which specific unit type is being trained. For example, BarracksSpawn (749407741) is used for all units from the Barracks - there's no way to distinguish Lancer vs Scout from the replay data alone.

## Field 4: Spawn Events

```protobuf
message SpawnEvent {
    optional uint32 owner = 1;        // Player slot owning the unit
    optional EntityId entity = 2;     // Entity identifier
    optional uint32 unit_type = 3;    // Unit type ID (171-174 observed)
}
```

## Field 37: Player Info

```protobuf
message PlayerInfo {
    optional EntityId id = 1;
    optional uint32 slot = 2;         // Player slot (1-4)
    optional string name = 3;         // Player display name
}
```

## Field 45: Profile/Chat

```protobuf
message ProfileData {
    optional SubData data = 5;
}

message SubData {
    optional string name = 1;         // Player name
    optional string player_id = 2;    // Numeric player ID string
}
```

## Field 40: Sync Data

```protobuf
message SyncData {
    optional uint32 counter = 1;      // Increments by 2048 each sync
    optional bytes checksum = 2;      // 5-byte checksum/hash
    optional uint32 counter2 = 3;     // Same as counter (first sync only)
}
```

## Map Information

Found in first message at path: `3 -> 1 -> 3 -> 2`

```protobuf
message MapInfo {
    optional string map_name = 2;     // e.g., "DesolateTemple"
    optional uint32 map_hash = 3;     // Map identifier
    optional uint32 unk5 = 5;
    optional uint32 unk6 = 6;
    optional uint32 unk7 = 7;
    optional uint32 unk10 = 10;
    optional uint32 changelist = 11;  // Game version CL
}
```

## Known Entity Type IDs

These are hash values observed in `target_type` and `ability_id` fields:

| Hash | Count | Likely Type |
|------|-------|-------------|
| 1318043485 | 8,832 | Common unit/ability |
| 890022063 | 2,438 | Unknown |
| 335308633 | 2,263 | Unknown |
| 1485475066 | 1,763 | Unknown |
| 923577301 | 1,713 | Unknown |
| 1954853105 | 1,318 | Unknown |
| 3191913349 | 950 | Unknown |
| 749407743 | 896 | Unknown |

*Note: These IDs are likely FNV-1a or similar hashes of internal asset names.*

## What IS Recorded

1. **Building construction**: Building type ID is recorded in field 4.3 (e.g., Barracks = 597044510)
2. **Attack/move positions**: Coordinates in fields 5-6 of target data
3. **Control group assignments**: Sequential IDs per player (e.g., 781263783-790)
4. **Ability usage**: Ability IDs map to runtime_session.json archetypes

## What is NOT Recorded

1. **Unit training type**: Spawn commands only record the spawn ability (e.g., "BarracksSpawn"), not which unit is queued (Lancer vs Scout)
2. **Resource counts**: Must be simulated from commands
3. **Unit positions over time**: Only command targets, not continuous tracking
4. **Game state snapshots**: Pure command log
5. **Selection state**: Control group IDs exist but selection contents aren't tracked

## Limitations

1. **Hash-based IDs**: Entity types use hashed identifiers requiring runtime_session.json for mapping
2. **Unknown UI action IDs**: Many target_type values (890022063, 923577301, etc.) are player UI actions not defined in runtime_session.json - likely control groups, camera positions, selection modifiers

## Decoding Example (Python)

```python
import zlib
import struct

def decode_varint(data, pos):
    result = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        result |= (b & 0x7f) << shift
        pos += 1
        if (b & 0x80) == 0:
            break
        shift += 7
    return result, pos

# Read file
with open('replay.SGReplay', 'rb') as f:
    header = f.read(20)
    magic = struct.unpack('<I', header[0:4])[0]
    changelist = struct.unpack('<I', header[12:16])[0]
    compressed = f.read()

# Decompress
decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
data = decompressor.decompress(compressed[10:])  # Skip gzip header (10 is common; robust parsers should parse gzip header flags)

# Parse messages
pos = 0
while pos < len(data):
    length, pos = decode_varint(data, pos)
    msg_data = data[pos:pos+length]
    pos += length
    # Decode msg_data as protobuf...

# Optional: bytes after the deflate stream (gzip trailer + possible appended protobuf footer)
unused = decompressor.unused_data
```

## Tools

Use `parse_sgreplay.py` to parse replays:

```bash
# Basic analysis
python parse_sgreplay.py replay.SGReplay

# Export all actions to JSON
python parse_sgreplay.py replay.SGReplay --json

# Quiet mode (JSON only)
python parse_sgreplay.py replay.SGReplay --json --quiet
```

## Version History

- CL107125: December 2025
- CL107146: December 2025
- CL107164: December 2025
- CL107172: December 2025

Format appears stable across these versions.
