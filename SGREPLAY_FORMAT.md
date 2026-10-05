# Stormgate replay format

Verified for **build 107842**, header version **2**. This supersedes earlier
speculative documentation for this build; older builds have a separate legacy path.

## Container

| Offset | Type | Meaning |
|---:|---|---|
| 0 | uint32 LE | Magic 0xE3B0A49D |
| 4 | uint32 LE | Header version 2 |
| 8 | uint32 LE | Header/data offset 20 |
| 12 | uint32 LE | Changelist |
| 16 | uint32 LE | Uncompressed footer byte length, NOT flags |

A single gzip member occupies the bytes between the header and footer. It includes
its CRC32/ISIZE trailer. The last footer_length bytes contain SPRecordingFooter,
without a length prefix. The native writer patches the header after appending it.

Decompressed data is a stream of unsigned-varint-length-prefixed
cf_ls_router.GameAction messages: field 1 timeStamp, field 2 clientID, field 3
netaction. NetActionBytes field 1 contains serialized ls_types.NetAction bytes.

## Identity and actions

Router clientID, participantId, and footer playerNumber are distinct namespaces.
The dashboard uses bootstrap client names and joins footer names only when unique
on both sides. It does not assume identical numbers across namespaces.

NetAction and NaParticipantAction use oneofs. Empty messages still represent
valid actions. Repeated entity IDs can be packed; they are not strings or guessed
nested protobuf messages. Optional presence is retained, including explicit false.

[The action reference](docs/ACTIONS.md) lists all 43 network variants, seven
participant variants, nested fields, and 65 explicit matching-map comparisons.

## Orders

PaSelectionOrder fields 1 through 8 are orderType, targetEntityId,
targetEntityKind, position, optional queued, optional smart, optional isAI,
and selectionIndex. Field 2 is not a build slot.

Order data encodes ability ID + command index. The matching map searches offsets
0 through 29 for the first known archetype. Its command array identifies the
requested unit or upgrade where applicable. A smart order with orderType zero is
context-sensitive; it cannot universally be labeled Move or Attack.

PaMapAction fields 1 through 7 are verb, optional data, optional subject,
optional kind, optional x, optional y, and selectionIndex. Meaning depends on verb:
UI data is not an ability, and quick macros need not use the current selection.

Coordinates are signed int32 using the SDK Distance scale of **16,384**.
Raw values and presence are preserved. Coordinate conversion and ability labels
are applied only to the exact bundled map-runtime hash.

## Footer

SPRecordingFooter fields: 1 maxSimTime, 2 mapName, 3 repeated players,
4 mapRuntimeHash.

| Player tag | Field |
|---:|---|
| 1 | playerNumber |
| 2 | displayName |
| 3 | team |
| 4 | factionType |
| 5 | endOfGameResult |

Results: 0 UNDECIDED, 1 WIN, 2 LOSS, 3 TIE, 4 FORCE_WIN, 5 FORCE_LOSS,
6 FORCE_TIE. Missing result means UNDECIDED. Team zero is valid.
Network tag 31 is endConnect, not a winner announcement. Tag 4 is beginConnect,
not a unit spawn.

## Coverage and limits

The strict path rejects unsupported builds, invalid gzip checksums, truncated
records, inconsistent header/footer boundaries, and unexpected trailing bytes.
Raw records and unknown-field counts are exported rather than silently discarded.
Commands describe requests, not successful outcomes. Complete world-state timelines
require simulation. Router ticks are retained; display timing follows the legacy
1024-ticks-per-second convention and is not the SDK's 64 Hz simulation step index.

See [the code investigation](docs/REVERSE_ENGINEERING.md) for evidence and limits.
