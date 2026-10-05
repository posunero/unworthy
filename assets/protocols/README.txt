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

These are derived from Frost Giant Studios game files, not original analyzer
code covered by this repository's MIT license. See docs/REVERSE_ENGINEERING.md.
No personal match data is included in this directory.
