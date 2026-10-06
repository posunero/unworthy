# Contributing

Install with `python -m pip install -e ".[dev]"` and run `python -m pytest -q`.
Use `python web/server.py` for the local dashboard.

## Evidence before interpretation

- Preserve raw values and optional-field presence.
- Add schema or handler provenance for new labels; do not infer entity ownership
  from targets or successful production from commands.
- Keep client IDs, participant IDs, and player numbers separate.
- Gate map-specific semantics by runtime hash. A build number alone does not
  prove two maps use the same catalog.
- Add synthetic binary fixtures for new interpretations and malformed inputs.
  Never commit personal replay files, names, chat, or generated match exports.
- Update the action reference with `python scripts/export_protocol_reference.py`.

## Extending coverage

The current corpus covers 98 exact map runtimes for build 107842, with Ashen
Boneyard as its reference catalog. Follow the reproducible extraction commands in
[the recovery audit](docs/RECOVERY_STATUS.md#reproduction) using locally extracted
game content. Another map/build needs its own provenance and compatibility tests.
The existing decoder deliberately refuses unsupported builds rather than silently
applying the wrong schema. Older builds continue through the legacy parser.

Remaining work includes nine original selector spellings, UI string-ID resolution,
precise recording/simulation time alignment, and runtime observations of order
success, movement, damage, and entity lifetime. Keep these gaps explicit.
