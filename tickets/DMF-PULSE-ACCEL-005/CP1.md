CP1 implements editable, nonsecret account evidence and immutable review output.
Unknown plan, entitlement, geography, credits, reset and other usage remain null.
Complete facts produce READY_FOR_INDEPENDENT_ACCOUNT_REVIEW, never a grant.

FPL replacement uses the isolated fresh-v2 slot, explicit fresh issuance and an
actual aware expiry. Setup does not read the old slot or compare secrets. Native
registration/expiry are checked under the mutation lock; expiry during write
removes only the fresh slot. Public CLI failures release the secret frame first.

Current source qualification extends the existing fixed enrollment resource;
the public registry is empty. The legacy FPL owner-risk profile cannot qualify
supplier permission, and the consumed historical Odds profile cannot qualify
the new purpose. Exact source/profile identity and actual validity time are
checked before reservation, before credentials and immediately before native
FPL transport. Grants expire no later than their source qualification. Owned
transport tests explicitly supply owned permission seams; separate denial tests
exercise the unmodified empty production registry.

Operator account evidence remains owner-reported and unverified. No account
secret, normal credential slot, authenticated quota endpoint, FPL endpoint or
football outcome endpoint was accessed. The manager identifier remains private.

Targeted evidence: CP1-TARGETED (166 passed), CP1-SOURCE-GATES (144 passed).
Independent scoped reviews retain both reproduced issues and corrected proofs.
Final whole-milestone review and installed/native acceptance remain CP6 gates.
