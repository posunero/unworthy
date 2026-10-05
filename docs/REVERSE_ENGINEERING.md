# How the game records replays

Findings apply to Windows **build 107842**. Addresses are preferred image
addresses from the recovered executable, not runtime addresses after ASLR.
Only derived metadata and the new decoder are included here. The decompiled
implementation remains in the local investigation workspace.

## Native recording path

1. `0x145432ad0` receives a game-action record. It returns for one caller-supplied
   condition, skips net-action tag 2 (heartbeat), and consults message options
   through `0x14543dbe0`. The first caller condition is not established here.
2. `0x145476ea0` passes the record to `0x146c4b5a0`. This obtains serialized size,
   rejects sizes at or above 2 GiB, writes an unsigned varint length, and serializes.
3. `0x14544d400` initializes magic, version 2, header length 20, changelist,
   and a zero footer-length placeholder. Deflate initialization uses windowBits
   31 (gzip). `0x145477050` writes the header as 12 + 4 + 4 bytes.
4. `0x14544fae0` feeds compression and writes output blocks.
5. `0x145447070` finishes compression, appends the serialized footer uncompressed,
   stores its size at header offset 16, seeks to zero, and rewrites the header.
6. `0x1454666c0` reads the footer from `file_size - footer_length` before restoring
   the stream position. It also has older-version branches not supported here.

## Recovered schemas

`cf_ls_router.GameAction` defines the outer record: field 1 `timeStamp`,
field 2 `clientID`, field 3 `netaction`. Its nested `NetActionBytes.bytes` field 1
contains the serialized `ls_types.NetAction`.

The old decoder guessed whether bytes were messages, strings, or opaque blobs.
The new decoder uses both recovered descriptors for packed IDs, signed int32,
UTF-8, and empty messages. Unknowns are checked in both envelope and action.

## Map and ability provenance

The bundled map catalog matches runtime hash
`1A899140C751370B2E7EE7B580671CDB1D5A4D22`, from module
`AshenBoneyard_245eeecf8bdc`. Source JSON and WASM SHA-256 hashes are recorded in
the catalog. Semantic decoding requires an exact footer hash match.

| Evidence | Finding |
|---|---|
| `order.h`, `AbilityOrderCommand::get_order_data` | Order data = ability ID + command index |
| `AbilityOrderCommand::from_order_data`, WAT line 255968 | First archetype found at offsets 0 through 29 wins |
| `snowplay/snowplay.h`, `max_command_index` | Exclusive bound is 30 |
| `snowplay/types.h`, `fnv1a_hash` | Name hashing is 32-bit FNV-1a |
| `snowplay/types.h`, `Distance` | Signed coordinate scale is 16,384 |
| `targeting_state_changed_event.h` | Named started/completed/canceled/inactive events |
| `on_action_shared`, WAT line 312708 / C line 557711 | 65 explicit map-verb comparisons |
| Dispatcher → `QuickMacro::execute` | Verb 81781465 is a quick macro request |
| Dispatcher → `QuickMacro::execute_smart` | Verb 1304751467 is a smart quick macro request |
| Dispatcher → `Events::UIEvent::broadcast` | Verb 3717677309 is UI data, not an ability |
| Dispatcher → `PlayerChatMessageEvent::broadcast` | Verb 429833619 is a chat notification |
| Unit handler → production ability → `ProductionQueueTask::on_action` | Verb 3703223256 passes data as queue index to `remove_from_queue(index, true)` |

See [ACTIONS.md](ACTIONS.md) for the complete descriptor inventory and all explicit
dispatcher comparisons, including branches whose names remain unresolved.

## Validation and remaining limits

The private reference replay yielded 1,742 complete records, 1,516 participant
actions, 348 gameplay commands, and no unknown protobuf fields. All its nonzero
order IDs and nine observed map verbs resolve. The 621 targeting transitions,
230 UI events, and 24 map chat notifications are not gameplay commands.
The personal replay is not committed.

This does not prove complete simulation understanding. UI string hashes remain
numeric. Smart orders depend on context. Quick macro unit choice, removal of dead
entities from selections, resources, damage, movement paths, completion, and
success require simulation. Commands are requests. Missing result means UNDECIDED;
a disconnect does not identify a winner.

The existing 1024-ticks-per-second display convention is retained for compatibility.
Router recording time is distinct from the SDK's 64 Hz simulation steps. Raw ticks
are exported; exact alignment across loading and pauses needs further validation.

## Reproduction

```bash
python scripts/build_action_catalog.py --content PATH/Stormgate/Content --module PATH/AshenBoneyard_245eeecf8bdc --output assets/protocols/ashen-boneyard-107842.json
python scripts/export_protocol_reference.py
python -m pytest -q
```

The catalog builder never reads replays. Tests include synthetic binary fixtures
for every network variant and semantic regression cases, so CI does not need
personal match files.
