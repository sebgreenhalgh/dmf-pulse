# Implementation result

`CurrentFplInputService` now compiles live parser-produced game settings without converting exact
Decimal values to binary float. The local adapter recursively preserves JSON objects and arrays,
maps finite Decimal values to normalized exact strings, retains null/boolean/integer/string
primitives, and fails closed for non-string object keys, non-finite Decimal values and arbitrary
runtime objects.

Equivalent Decimal text forms and object orders produce the same canonical semantic hash. The
existing integer-only fixture retains canonical JSON
`{"league_join_private_max":30,"squad_squadplay":11}` and semantic SHA-256
`cb1c285a7b527f6cc1cf6ba7fe69def9e6cc6c85eb5a6bca59c9ec84091dfc69`. Manual-file and
direct-memory compilation produce identical game-settings semantics. The parser, generic
canonical serializer, Odds, authentication, score prior, optimiser, captaincy, and one-command
architecture are unchanged.

The real source-tree and externally installed wheel both compiled the current GW3 bootstrap and
fixtures. Both produced a 1,052-byte canonical game-settings JSON document with semantic SHA-256
`62cbe4f8e9b01faeee8e78e054839e68c78b8d9d03484498e4e2ee92d56e816f`. The public-first snapshot
continued through the six public endpoint classes and stopped at the expected missing bearer-token
boundary, proving the former current-input assembly failure is fixed.
