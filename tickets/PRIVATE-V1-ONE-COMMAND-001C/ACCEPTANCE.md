# PRIVATE-V1-ONE-COMMAND-001C engineering acceptance

The FPL parser's contract projection and declared artifact transformation must recurse through
ordinary string-keyed JSON dictionaries as well as models, lists and tuples. Nested Decimal
values retain the parser's existing exact string representations; semantic projection never
converts them to binary float. Nested datetimes remain UTC RFC 3339 strings. Non-string mapping
keys and non-finite JSON numbers fail closed.

The hotfix preserves existing frozen FPL semantic hashes when the added recursion has no semantic
effect and leaves the repository-wide canonical serializer unchanged. Acceptance requires focused
and affected regressions, branch coverage and static gates; a real Windows/Python 3.13 bootstrap
fetch and parse through `DirectFplClient`; public-first snapshot progression beyond bootstrap;
installed-wheel, repository and secret checks; a pushed isolated branch; and exact-final-SHA CI
success. No real response body, entry identifier or credential may be retained.
