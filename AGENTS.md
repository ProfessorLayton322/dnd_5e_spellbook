# Agent instructions

## Repository invariants

- The application is offline at runtime. Spell data is generated ahead of time and bundled in `src/spellbook_builder/data/spells.json`.
- JSON files are ignored by default. The bundled `spells.json` file is the one intentional tracked exception.
- Never commit `dist/`, `build/`, Gradle output, runtime spellbooks, signing keys, `keystore.properties`, or other generated packages/secrets.
- Committed PDF batches are immutable. Only the table of contents and full-PDF assembly may be regenerated.
- Preserve unrelated user changes in a dirty worktree.

## Verify changes

Use the project virtual environment and run the complete suite before delivery:

```bash
.venv/bin/python -m pytest
.venv/bin/spellbook validate-index
```

For code or bundled-data changes, rebuild both native packages:

```bash
scripts/build_all.sh
```

The build writes the Windows installer and Android APK to ignored `dist/`. The machine-local toolchain is loaded by `scripts/toolchain-env.sh`; override its location with `DND5E_TOOLCHAIN_ROOT` when necessary.

## Commit, push, and release routine

Finish repository work instead of leaving it only in the working tree:

1. Inspect `git status` and the staged diff; include source, tests, documentation, and intentional bundled-data updates.
2. Keep build products and signing material out of Git.
3. Commit the verified change with a concise imperative message.
4. If `origin/main` already exists, run `git pull --rebase origin main` and resolve conflicts without discarding user work.
5. Push the commit directly with `git push origin HEAD:main`.
6. Read the version from `pyproject.toml`. Create or update release `v<version>` with the matching files from `dist/` using `gh release create` or `gh release upload --clobber`.
7. Confirm that `origin/main` points at the local commit and that both release assets are present.

The source of truth is GitHub `main`; installable `.exe` and `.apk` files belong in the matching GitHub Release, not in repository history.
