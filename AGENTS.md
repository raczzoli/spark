# Local build workflow

- Update the current build in `release/app/` and `release/pico-firmwares/`.
- Do not create `release-candidate/` folders or another output directory for each change unless the user explicitly asks for one.
- For UI-only changes, retain existing verified firmware files unchanged.
- Do not push to GitHub unless the user explicitly requests it.
- UI tests/previews must use temporary settings and must not save sample battery selections or readings into the user's app settings. Battery selection starts empty for each application session.
