# Known limitations and open questions

No unresolved implementation defect blocks FND-001.

- GitHub-hosted CI and human acceptance were not triggered by Codex; the complete equivalent local gate is recorded and passed.
- `Europe/London` has a bundled standard-library fallback. Other configured IANA display zones require timezone data from the host Python installation.
- A ZIP cannot contain its own final cryptographic digest. `codex_result.review_pack.sha256` therefore records the validated stable digest over primary files 04-05 and 07-19; the final archive SHA-256 is reported externally after validation. Inside the ZIP, the detached manifest hashes files 01-02 and 04-19, while file 20 hashes files 01-19, breaking the manifest/checksum cycle while validating every payload.
- Merge, push, release tag, and production activation remain human-controlled and were not performed.
