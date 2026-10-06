# Unworthy · Stormgate Replay Analyzer

Understand what a replay actually records: commands, selections, targets, queues,
control groups, targeting transitions, chat, and system events.

**Build 107842 now uses recovered game schemas.** The normal CLI and local dashboard
use the verified decoder automatically for that build. Exact-map ability semantics
are available for 98 recovered map runtimes, selected by exact runtime hash.
Unknown runtimes retain named protocol fields and raw IDs. Older builds use the
legacy heuristic parser.

## Quick start

Requires Python 3.11 or newer.

```bash
git clone https://github.com/posunero/unworthy.git
cd unworthy
python -m pip install -e .
python parse_sgreplay.py path/to/replay.SGReplay --json
```

Or use `uv sync` and prefix commands with `uv run`.

### Local dashboard

```bash
python web/server.py
```

Open the local address printed by the server (default port 8080). Select a replay
folder or inspect one match. Windows replays normally live in
`%LOCALAPPDATA%\Stormgate\Saved\Replays`.

### Complete decoded export

```bash
python recovered_replay.py path/to/replay.SGReplay --output decoded.json --text timeline.txt
```

Installed command: `sgreplay-decode`. The export includes every raw record, its
named fields, observed selections, resolved ability/command pairs, provenance,
and coverage counts. The readable timeline separates gameplay commands from
UI, targeting, chat, selections, and system traffic.

## What is supported

| Capability | Status |
|---|---|
| Container, gzip integrity, footer boundaries | Verified v2 / build 107842 |
| Network action variants | All 43 decoded from recovered descriptors |
| Participant action variants | All 7, including packed selection/control-group IDs |
| Map dispatch surface | All 66 explicit entry selectors across 98 modules, with source-traced descriptions |
| Original selector names | 57 retained names; nine use documented behavioral descriptions |
| Ability commands | Hash + command index, resolved against the exact matching map catalog |
| Coordinates | Signed int32 / 16,384 for the matched catalog |
| Selection tracking | Recorded changes per participant and selection index |
| Results | Footer result enum; absent means undecided |
| Older builds | Legacy heuristic behavior, not validated by the new schema |
| Movement paths, damage, resources, successful completion | Require simulation; not inferred from command counts |

A build/train/research event is a **request**, not proof of completion. Smart
orders require world state to determine their eventual behavior. UI string hashes
remain numeric without a corroborating dictionary. Zero unknown wire fields
is a coverage check, not a claim of perfect gameplay reconstruction.

## Why this decoding is different

The old format assumptions confused connection records with spawns, team fields
with results, and UI/map data with ability IDs. The new path follows the native
recording writer and two recovered protobuf descriptors. It preserves optional
presence, validates complete records, and gates gameplay names on map runtime hash.

- [Replay format](SGREPLAY_FORMAT.md)
- [All protocol actions and map dispatcher entries](docs/ACTIONS.md)
- [Source recovery coverage and documented limits](docs/RECOVERY_STATUS.md)
- [Native recording path, evidence, and remaining gaps](docs/REVERSE_ENGINEERING.md)
- [Contribution and validation guide](CONTRIBUTING.md)

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
python scripts/export_protocol_reference.py
```

CI runs on Windows and Linux with Python 3.11 and 3.14. Synthetic replay fixtures
cover every network variant, corruption, optional flags, signed coordinates,
ability command indices, map-version gating, and dashboard integration. Personal
replays are ignored by Git; optional local replay checks skip when absent.

| File | Purpose |
|---|---|
| `recovered_replay.py` | Strict container and descriptor decoding; readable timeline |
| `verified_summary.py` | Verified records adapted for the existing dashboard |
| `parse_sgreplay.py` | Shared CLI and legacy compatibility |
| `assets/protocols/` | Recovered descriptors, 98 map catalogs, and source audit |
| `scripts/recover_action_surface.py` | Reproducible entrypoint and handler inventory |
| `scripts/build_catalog_corpus.py` | Exact-runtime catalog extraction |
| `web/` | Local dashboard |
| `tests/` | Public synthetic fixtures and regression tests |

The analyzer code is MIT-licensed. Stormgate and the recovered schema/catalog
metadata originate from Frost Giant Studios; this project is unofficial.
