# Verification vectors

TEST ONLY. The Ed25519 keys in `vectors.json` are fixtures. They are not
production signing keys and must not be deployed. The verifier key and the
reviewer approval key are separate authorities.

`octopus-kb` authors this directory. The parser copies it byte for byte.
Both repositories pin its SHA-256. The digest is SHA-256 over the sorted
file names in this directory. For each file the input is the UTF-8 name,
a NUL byte, the file bytes, and a NUL byte.
