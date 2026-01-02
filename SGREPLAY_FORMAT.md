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
- **Gzip header** (10 bytes): `1F 8B 08 00 00 00 00 00 00 0A`
- **Deflate-compressed data**: Raw deflate stream (use zlib with -MAX_WBITS)

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

- Field 1 is the timestamp in **milliseconds** from game start
- To convert to seconds: `frame / 1000`
- To convert to mm:ss: `minutes = frame / 60000`, `seconds = (frame / 1000) % 60`

### Player ID

- Values 1-5: Player slots
- Value 64: System/global messages (game setup, spawns)

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
    optional uint32 unk3 = 3;         // Usually 0
    optional uint32 unk4 = 4;         // Usually 0
    optional uint32 unk5 = 5;         // Usually 0
    optional uint32 unk6 = 6;         // Usually 0
}
```

### Field 7 -> 4: Ability Data

```protobuf
message AbilityData {
    optional uint32 ability_id = 1;   // Ability type hash
    // Additional fields vary
}
```

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

## Limitations

1. **No resource tracking**: Resources must be simulated from commands
2. **No unit positions**: Only target IDs, not coordinates
3. **No game state snapshots**: Pure command log
4. **Hash-based IDs**: Entity types use hashed identifiers, not human-readable names

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
data = decompressor.decompress(compressed[10:])  # Skip gzip header

# Parse messages
pos = 0
while pos < len(data):
    length, pos = decode_varint(data, pos)
    msg_data = data[pos:pos+length]
    pos += length
    # Decode msg_data as protobuf...
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
