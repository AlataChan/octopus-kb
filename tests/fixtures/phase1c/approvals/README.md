# Approval vectors

TEST ONLY. The Ed25519 key in `vectors.json` is a fixture. It is not a
production signing key and must not be deployed. `octopus-kb` copies this
directory and checks its digest. It does not fetch `/v1/approvals/keys`
as a trust bootstrap.
