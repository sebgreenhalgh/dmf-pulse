# Historical L3 boundary

The terminal evidence proves only that shadow preparation succeeded sufficiently
to start comparison invocation and that invocation did not return normally. The
parent's D1 and D2 typed signals inherited from `ValueError`; the one-command layer
therefore converted either signal to its ordinary `ONE_COMMAND_INPUT_INVALID`
error before the outer service could serialize the diagnostic.

This mechanism erased the detailed historical failure. It does not establish which
D1/D2 stage or reason occurred. The exact underlying L3 comparison failure remains
unknown. L3 is consumed and D3 creates no L4 authorization.
