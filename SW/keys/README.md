# Signing Keys

MCUboot ED25519 image signing keys, verified via the nRF54L15 hardware KMU.

## Files

| File | Purpose |
|------|----------|
| `dev.pub` | Dev public key (revokable) |
| `prod.pub` | Production public key (revokable) |
| `prod2.pub` | Secondary production public key (non-revokable) |
| `provision-dev.yml` | KMU provisioning: dev + prod + prod2 |
| `provision-prod.yml` | KMU provisioning: prod + prod2 only |

Private keys (`*.pem`) are gitignored. Production private keys should be stored in an HSM or other secure mechanism. The secondary production key is not used normally, it is a backup in case the primary production key is leaked and must be revoked.

## Key Slots (KMU)

Slot base address: 242 (`BL_PUBKEY`).

| Slot | Dev build | Prod build |
|------|-----------|------------|
| 242 (gen0) | dev.pub | prod.pub |
| 244 (gen1) | prod.pub | prod2.pub |
| 246 (gen2) | prod2.pub | — |

## Provisioning

Run from `SW/` (workspace root) — the YAML key paths are relative to cwd. Requires a full chip erase if previously provisioned with different keys.

```sh
# From SW/
nrfutil device erase --all
west ncs-provision upload -i keys/provision-dev.yml   # dev device
west ncs-provision upload -i keys/provision-prod.yml  # production device
```

## Generating New Keys

```sh
imgtool keygen -t ed25519 -k keys/<name>.pem
imgtool getpub -k keys/<name>.pem -o keys/<name>.pub
```

## Build Integration

Relative paths in `SB_CONFIG_BOOT_SIGNATURE_KEY_FILE` resolve from `WEST_TOPDIR` (the workspace root, `SW/`). Dev builds sign with `keys/dev.pem`; production builds (`-DSB_EXTRA_CONF_FILE=sysbuild_extra_production.conf`) sign with `keys/prod.pem`.
