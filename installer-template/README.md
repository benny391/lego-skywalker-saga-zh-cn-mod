# Installer template

1. Copy `manifest.example.json` to `manifest.json`.
2. Fill in exact official, target and patch SHA-256 values and archive sizes.
3. Place generated `.gpatch` files under `patches/`.
4. Test installation and uninstallation against disposable copies before distribution.

The scripts refuse unknown source versions, verify temporary target files before replacement, and keep verified backups for rollback.
