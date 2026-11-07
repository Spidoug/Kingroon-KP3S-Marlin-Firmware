# Publishing the source on GitHub

This archive is **repository-ready source**, not a precompiled/verified firmware release.

## Before making it public

- Confirm you own or can redistribute all photos and diagrams under `assets/`, and verify notices for any third-party material.
- Confirm repository ownership and the desired project URL. The README intentionally contains no unverified CI-success badge.
- Check that no printer credentials, EEPROM backups, personal data, private keys, `.bin` files, downloaded Marlin archives or generated toolchains are being committed.
- Run the offline checks from [`validation.md`](validation.md), review `.github/workflows/` and decide whether to enable private vulnerability reporting in repository settings.
- **Do not label the firmware hardware-validated** without the required Marlin compile and supervised printer acceptance checks.

## Create a new repository

From inside the extracted `Kingroon-KP3S-Marlin-Firmware/` directory:

```bash
git init -b main
git add .
git status --short
git commit -m "Prepare KP3S V1 Nokia/Samsung source for GitHub"
# Then create an empty repository in GitHub (without initializing a README).
git remote add origin https://github.com/YOUR-ACCOUNT/Kingroon-KP3S-Marlin-Firmware.git
git push -u origin main
```

Replace `YOUR-ACCOUNT` with your actual GitHub account. These commands create a **new repo**; if a repository already exists with history, integrate changes through a branch/PR rather than force-pushing.

The normal CI runs **offline checks only**. `manual-firmware-build.yml` can be started by a maintainer from GitHub Actions to attempt a **stock-profile full build** and attach the resulting artifact. Successful CI does not establish actual board or hotend compatibility; the manual workflow never flashes a printer.

Recommended topic keywords: `kingroon-kp3s`, `marlin`, `nokia-5110`, `samsung-ue5000`, `stm32`, `3d-printer`, `firmware`.
