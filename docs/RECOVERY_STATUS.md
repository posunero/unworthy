# Source recovery status and limits

## Conclusion

The finite, explicit replay-entry action surface has been inventoried and assigned
source-based handler descriptions. A claim that **every possible action effect is
fully recovered** is not justified by these exports. The decoder therefore keeps
raw data, attaches runtime requirements, and makes no success/completion claims.

This is not a claim that further recovery is permanently impossible. Running the
matching simulation, reconstructing its state, or obtaining additional symbols
can resolve many of the remaining questions. A context-free replay parser alone
cannot supply those answers.

## What was checked

| Layer | Coverage | What the count means |
|---|---:|---|
| NetAction schema | 43 variants | Every recovered oneof field, including messages normally filtered from recordings |
| Participant schema and native bridge | 7 variants | Native cases 2, 3, 4, 9, 11, 12, 14 traced in `0x1800c9110` |
| Shared map dispatch | 65 selectors | Explicit equality/inequality guards on the action verb |
| Exported map entrypoint | 1 additional selector | `4279446118`; absent from the earlier 65-entry catalog |
| Map modules | 98 | Each C inventory independently agrees with its WAT inventory |
| Named internal action handlers | 215 distinct names / 20,864 occurrences | Locations inventoried; these are not additional direct replay message types |
| Retained map-action names | 57 of 66 | Matching native binary strings or shipped header literals, with offsets/lines |
| Exact runtime catalogs | 98 | Build 1.0.107842, selected by footer runtime hash |
| Defined ability-command slots | 91,902 across maps | Repeated map-specific slots, not distinct executable actions |

The exported `on_action` implementation is identical across the 98 modules after
normalizing the module namespace. It handles the extra selector then forwards to
`on_action_shared`. The reference shared dispatcher initializes its return value
to zero and returns it on the unmatched default path. Arbitrary uint32 verb
values are wire-decodable; an absent explicit handler is not a newly discovered
gameplay action. Other/custom/future map binaries are outside this inventory.

The compressed [source inventory](../assets/protocols/source-action-audit.json.gz)
records every module hash, entrypoint location, C/WAT comparison check, and named
internal action-handler location. [ACTIONS.md](ACTIONS.md) gives a disposition for
each of the 66 selectors: behavior, payload mode, evidence, and required state.
No remaining branch is silently labeled as an unnamed gameplay command.

## Native bridge findings

`snowplay_dll_UnrealShipping.dll`, preferred address `0x1800c9110`:

| Participant action | Native behavior |
|---|---|
| setSelection | Temporarily selects selectionIndex, clears/adds requested members, emits participant_selection_changed, restores the prior index |
| modifySelection | Temporarily selects selectionIndex, removes then adds members, emits selection-changed, restores the prior index |
| selectionOrder | Selects command, command_queued, smart_command, or smart_command_queued from queued/smart; forwards order/target/position; restores the prior selection index |
| mapAction | Forwards verb/data/subject/kind/x/y under the requested selection index and restores the old index |
| setControlGroup | Rejects indices above 10; clears then adds members |
| modifyControlGroup | Rejects indices above 10; removes then adds members |
| setBotOptions | Packs currentlyActive/buildWorkers/maintainSupply/buildStructures/buildArmy/buildExpansion into bits 0 through 5 of set_bot_options.data |

Bot field offsets were independently checked against protobuf serializer
`0x1801857a0`: offsets 0x10 through 0x15 serialize fields 1 through 6.
The selection-order branch does not read isAI; that field remains in the decoded
record and is not used to invent a command_ai dispatch. Participant-active/player
binding checks and entity validation still require runtime state. The exported
selection membership is **requested membership**, not a certified simulation snapshot.

## Recording filter findings

The writer `0x145432ad0` excludes heartbeat and consults `0x14543dbe0` before writing.
The option number read at executable address `0x1491399e8` is **51239**, matching
the recovered `ephemeralNetAction` extension. Its false default is stored at
`0x1491399ec`. Thus heartbeat, requestAnnounceNextSynchronized, resultRequest,
resultResponse, and echo are excluded by this path. The decoder still recognizes
their wire schemas. A separate caller flag can also suppress writing; its original
symbolic name is not established. This does not alter the decoded action schemas.

## What cannot be supplied from a record alone

| Gap | Concrete reason / source evidence | What would resolve it |
|---|---|---|
| Unit identity, ownership, and lifetime | Entity IDs reference simulated entities; `Participant::can_command`, entity validation and ability dispatch consult world state | Matching replay simulation or an equivalent state reconstruction |
| Smart-order choice and path | `UnitTask::on_smart_command` and selection/movement handlers choose by context; zero orderType is not universally Move | State and actual handler execution |
| Quick macro acting unit and success | `QuickMacro::execute` / `execute_smart` choose eligible units at runtime | Runtime unit/queue/resource state |
| Accepted selections/control groups | Native mutation checks live entities and participant binding; the file records requests | Observe accepted native selections; static group-index rejection is already modeled |
| UI/widget/VM strings | These records contain String IDs, not necessarily the original text. A 32-bit ID does not uniquely determine arbitrary text | Runtime string dictionary or corroborating retained literals; never fabricate a preimage |
| Event subscriber effects | Camera, widget, VM and sequence broadcasts invoke registered handlers and filters. Static targets were recovered where available (e.g. table indices 2605/2610 for VM/widget in the reference module) | Subscriber/filter state and execution. An indirect call does not mean all targets are unknowable |
| Nine original selector spellings | Not found as matching strings in the scanned native ASCII/UTF-16 pools or shipped headers; behavioral rules are still recovered | Additional symbols/source or corroborating literals. Descriptive labels remain explicitly labeled |
| Map-specific flag name | Exported on_action sets key 2001821935 on player slot 4 for verb 4279446118; the operation is known, the original key spelling is not | Original symbol/string dictionary. The numeric write is preserved |
| Damage, resources, completion, deaths | Command submission does not certify execution or success; generated triggers and state affect outcomes | Full simulation trace |
| Exact recording-to-simulation time | Router timestamps and 64 Hz simulation steps are distinct; loading/pauses affect alignment | Validated synchronization reconstruction. Raw ticks and checksum messages are retained |
| Global native-code completeness | Recovery metadata reports 79 failed native exports and a 900-second analysis timeout | Further disassembly/decompilation and runtime checks. This is not evidence that those failures specifically contain replay actions |

The SDK's `on_unhandled_map_action` snippet in `static_multicast_delegate.h` is
an **example**, not evidence that the shipped map has such a fallback. The audit
uses the actual compiled entrypoints instead.

## Reproduction

```bash
python scripts/recover_action_surface.py --modules PATH/map-code --output surface.json
python scripts/recover_action_names.py --binaries PATH/binaries --sdk PATH/Content/data/tasks/public --output assets/protocols/action-name-evidence.json
python scripts/build_source_audit.py --modules PATH/map-code --surface surface.json --output-dir assets/protocols
python scripts/build_catalog_corpus.py --content PATH/Content --reference assets/protocols/ashen-boneyard-107842.json --output assets/protocols/map-catalogs-107842.json.gz
python scripts/export_protocol_reference.py
python -m pytest -q
```

The source-name scanner enforces the SHA-256 hashes of the exact analyzed native
binaries. Catalogs contain derived metadata, not personal replay content. Synthetic
tests exercise all 66 selectors, all seven native bridge kinds, queued/smart
combinations, bot flags, invalid groups, typed UI/camera payloads, and map-hash
isolation. None of these tests claims execution equivalence with the entire game.
