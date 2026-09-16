# R9C-D1 acceptance contract

Parent is `32dc27ff78cf492c14e41e17d542fdde95691a9a`. This ticket adds a closed
operator-facing failure taxonomy to the dedicated R9B shadow probe only.

- No FPL/Odds request, credential inspection, probe, recommendation or activation
  is permitted during implementation.
- Blocked output contains only finite stage/reason enums and fixed aggregate flags.
  It has no error-details, exception, URL, path, body, header, identity or credential field.
- Existing client request count is preserved at the failure boundary; no diagnostic
  request or whole-probe retry is allowed.
- R9B posterior/compiler/resource and rights metadata remain byte-identical.
- Success keeps its aggregate R9B output; active recommendation remains untouched.
- Publish only after offline tests, independent read-only clearance and exact-SHA CI.
