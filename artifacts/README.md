# Offline evidence archives

Large self-contained archives are generated locally and excluded from Git. Their checksum files are
tracked, and the Stage 3 archive metadata and two-rebuild verification record are published in
`evidence/stage3/archive.json`.

Recreate and verify the formal Stage 3 archive with:

```sh
./seedbridge study-export runs/stage3-formal-02 --output artifacts/stage3-formal-v1.tar.gz
./seedbridge study-verify-archive artifacts/stage3-formal-v1.tar.gz \
  --output runs/stage3-formal-offline-verify-01
```

Both output paths must be new. The archive contains its own `OFFLINE_README.md`, per-file manifest,
frozen execution source, compact raw records, and standard-library rebuild script.
