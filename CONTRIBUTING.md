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

The current derived catalog covers the matching Ashen Boneyard runtime for build
107842. Rebuild it using `scripts/build_action_catalog.py` and locally extracted
game content. Another map/build needs its own provenance and compatibility tests.
The existing decoder deliberately refuses unsupported builds rather than silently
applying the wrong schema. Older builds continue through the legacy parser.

Important remaining work: unresolved dispatcher names, UI string-ID resolution,
precise recording/simulation time alignment, and runtime observations of order
success, movement, damage, and entity lifetime. Keep these gaps explicit.
