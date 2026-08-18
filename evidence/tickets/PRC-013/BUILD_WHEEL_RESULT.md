# Build and installed-wheel result

Canonical command `uv run python -m build`: **PASS**.

- Wheel: `dmf_pulse-0.2.0-py3-none-any.whl`
- Size: 687335 bytes
- SHA-256: `517ab108cebfdf2d65e88c3a0c002cc77800dd281ee4fb09410b53e65e985a60`
- Wheel ZIP integrity: PASS; 249 members.
- Sdist: 3435828 bytes; SHA-256
  `1d816e574fbb63914c711b4bf05a0c9831d12bb55eafbdc96cd6524efedb97d1`.
- Required installed members present: packaged price YAML, service and CLI.

The wheel was installed into a new Python 3.13 environment under the operating-system temp root,
outside the source tree. It installed 23 packages and imported `dmf_pulse` from that environment's
`site-packages`; no source-tree import or `PYTHONPATH` was used.

## Final main integration

The integrated canonical build is **PASS**.

- Wheel: 697057 bytes; 250 members; SHA-256
  `944c4c3d6792ec0beb5a0ef6d04318990575681967278a253fd62db8b06ebfa3`.
- Sdist: 3723843 bytes; SHA-256
  `e1865ed8078efbaf7cf0f09c60389d36c4dd37ddc946e3adc62aab6bd414506d`.
- Packaged and repository price configurations are byte-identical at SHA-256
  `e2ed7e94eec15ec61a641e02ea073264c46d0447cb8a4e06096f3c4de82e7705`.
- A new external Python 3.13 environment installed 23 packages and imported only from its
  `site-packages`, with repository `PYTHONPATH` removed.
