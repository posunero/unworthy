Recovered build-107842 metadata

ls_types-107842.pb: serialized FileDescriptorProto for network actions,
participant actions, simulation events, and recording footer.
Source recovery: e900ea9cd3fb-ls_types.proto.descriptor.pb

cf_ls_router-107842.pb: serialized FileDescriptorProto defining GameAction
and NetActionBytes, the actual recording envelope.
Source recovery: a5ce5d7c1e24-cf_ls_router.proto.descriptor.pb

ashen-boneyard-107842.json: derived archetype IDs, command references, and
65 explicit map dispatcher comparisons. Includes source hashes and provenance.
Rebuild with scripts/build_action_catalog.py; no replay files are consumed.

action-semantics-107842.json: reviewed behavior, payload roles, source locations,
and runtime requirements for all 66 entry selectors, superseding the reference
catalog's earlier 65-selector mapVerbs table at load time.
action-name-evidence.json: retained native/header names for 57 selectors.
source-action-audit.json.gz: C/WAT entry-selector agreement across 98 modules,
normalized exported-entrypoint hashes, and internal-handler source locations.
map-catalogs-107842.json.gz: 98 exact-runtime archetype catalogs stored as deltas
against the reference. The canonical archetype digest validates the base across
line-ending conversions; raw source-file hashes are provenance only.
See docs/RECOVERY_STATUS.md for reproduction commands and limits.

These are derived from Frost Giant Studios game files, not original analyzer
code covered by this repository's MIT license. See docs/REVERSE_ENGINEERING.md.
No personal match data is included in this directory.
