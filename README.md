# Offline D&D 5e Spellbook Builder

A local-first Windows, Android, browser, and CLI application for assembling Russian D&D 5e spell lists and exporting stable printable PDFs. The spell catalogue is downloaded from [dnd.su](https://dnd.su/spells/) at build time and bundled as JSON, so an installed app does not need a network connection.

The workflow and PDF storage model intentionally follow the sibling `dnd_35_spellbook` project:

- spells can be added individually with Russian/English prefix suggestions, or as an entire class/level list;
- an open batch is editable, but a committed batch is immutable;
- spells flow into available page space on a best-effort basis instead of forcing one spell per page;
- each later batch starts on a fresh logical content page;
- a full PDF is a newly rendered table of contents followed by unchanged batch segments;
- every commit also exports the complete current TOC, an exact copy of only the new segment, and a hash manifest.

## Run from a checkout

Python 3.12 or newer is required.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/spellbook serve
```

Open <http://127.0.0.1:8000>. On Windows, use `.venv\Scripts\python.exe` and `.venv\Scripts\spellbook.exe`.

Runtime state defaults to `runtime/`. Override it with `DND_SPELLBOOK_RUNTIME` or the global CLI option:

```bash
.venv/bin/spellbook --runtime /path/to/data serve
```

The packaged desktop app uses `%LOCALAPPDATA%\DnD5eSpellbook\runtime` on Windows. Android uses private application storage.

## Download and bundle the spell catalogue

The committed file at `src/spellbook_builder/data/spells.json` is the application catalogue. Regenerate it with:

```bash
.venv/bin/python scripts/download_spells.py --refresh
```

The downloader:

1. reads the site's public `sitemap.xml` and selects numeric `/spells/<id>-.../` pages;
2. requests only official spell detail pages, with a descriptive user agent, spacing, retries, and timeouts;
3. parses the semantic spell card rather than navigation, comments, or page chrome;
4. stores names, level, school, ritual/concentration flags, parameters, class lists, source, description blocks, and plain-text tables;
5. atomically checkpoints `spells.json` after every new page.

An interrupted run resumes from existing records. `--refresh` re-downloads everything, while `--limit N` is useful for parser work. The script deliberately does not use dnd.su's internal `/piece/` endpoint because the site's `robots.txt` disallows it.

The resulting JSON and all fonts are package data in `pyproject.toml`; the Windows and Android builders copy them into the binary application. The runtime has no mutable spell index and never downloads spells.

## Build a spellbook

1. Create and select a spellbook.
2. Begin a batch.
3. Search by the beginning of a Russian or English name, or add a complete class/level list.
4. Remove mistakes while the batch is open.
5. End the batch to render its immutable segment and refresh the exports.

Duplicate spells in one open batch are ignored. Committed batches cannot be edited. Deleting an entire spellbook removes its segments and exports after confirmation.

## Append-only PDF layout

Every commit creates:

```text
runtime/spellbooks/<book-id>/
  batches/batch-0001.pdf       immutable content segment
  full.pdf                     fresh TOC + all immutable segments
  exports/batch-0001/
    toc.pdf                    complete current TOC only
    append.pdf                 byte-for-byte copy of the new segment
    manifest.json              logical ranges, entities, versions, hashes
```

Content page numbering begins at 1 and excludes physical TOC pages. A segment begins at the previous batch's `page_end + 1`. Within a segment, spell bodies flow continuously; a separator, title, subtitle, and first details line move together when they do not fit at the bottom of a page. Long spells continue naturally onto later pages. The bundled DejaVu fonts preserve Cyrillic text on every target platform.

`verify-append-only` checks immutable segment hashes, exact append copies, contiguous logical ranges, and each full-PDF content stream against its source segment:

```bash
.venv/bin/spellbook verify-append-only my-book
.venv/bin/spellbook render-spellbook my-book
```

`render-spellbook` refreshes only the TOC/full assembly. It never rewrites historical segments.

## Other CLI commands

```bash
.venv/bin/spellbook dataset-info
.venv/bin/spellbook validate-index
.venv/bin/spellbook list-spells --prefix огн --limit 25
.venv/bin/spellbook list-spells --prefix fire --limit 25
```

## Build the Windows app

The builder downloads checksum-pinned Windows embeddable Python and pinned Windows wheels, copies this repository's `spellbook_builder` package, and invokes NSIS. It needs Python 3.11+ with pip, internet access, and NSIS 3 (`makensis`):

```bash
python3 packaging/windows/build.py
# dist/DnD5eSpellbook-0.1.0-Setup.exe
```

The installer is per-user and needs no administrator rights. It adds app-window and browser shortcuts. The app window uses Microsoft Edge WebView2 when available and falls back to the default browser. End users do not need Python.

## Build the Android app

`packaging/android` is a Gradle/Chaquopy project which embeds Python 3.13, the web application, the spell JSON, and PDF fonts. It requires JDK 17, Android SDK 35 via `ANDROID_HOME`, and Python 3.13 on `PATH` (or `-Pspellbook.buildPython=/path/to/python3.13`):

```bash
packaging/android/build.sh
# dist/DnD5eSpellbook-0.1.0.apk
```

The first build creates private signing files under `~/.local/share/dnd5e-spellbook/signing` (override with `DND5E_SIGNING_DIR`). Back them up because Android upgrades must be signed with the same key. The APK supports Android 7.0/API 24 or newer and includes ARM64 and x86-64 ABIs.

The Android shell runs the localhost server in a foreground service, displays the UI in a WebView, and supports opening, saving, or sharing generated exports.

## Build both packages on this machine

The user-local toolchain is installed under `~/.local/share/dnd5e-spellbook/toolchain`. It contains CPython 3.13, OpenJDK 17, Android API/build tools 35, and NSIS 3 without requiring administrator access. Load it explicitly for individual build commands:

```bash
source scripts/toolchain-env.sh
python3.13 packaging/windows/build.py
packaging/android/build.sh -Pspellbook.buildPython="$(command -v python3.13)"
```

Or build both release packages in one command:

```bash
scripts/build_all.sh
```

The resulting installer and APK are written to the ignored `dist/` directory. Android signing files remain outside the repository under `~/.local/share/dnd5e-spellbook/signing` and must be backed up privately for future upgrades.

## Tests

```bash
.venv/bin/pytest
```

The local suite covers sitemap/detail parsing, Cyrillic and English search, bundled-data validation, web workflow, flowing PDF placement, immutable historical segments, exact append exports, and full-PDF verification. It does not contact dnd.su.

## Project layout

```text
scripts/download_spells.py              resumable catalogue builder
src/spellbook_builder/data/spells.json  bundled offline catalogue
src/spellbook_builder/dndsu.py           semantic dnd.su parser/crawler
src/spellbook_builder/store.py           user state and immutable segment paths
src/spellbook_builder/service.py         batch commit/export/verification logic
src/spellbook_builder/pdfgen.py          Cyrillic PDF content and TOC renderer
src/spellbook_builder/web.py             localhost FastAPI UI
src/spellbook_builder/desktop.py         Windows desktop/browser launcher
src/spellbook_builder/mobile.py          Android entry points
packaging/windows/                       Windows installer builder
packaging/android/                       Android APK builder
```

Spell text and translations obtained from dnd.su remain subject to their respective owners' rights. Review redistribution permission before publishing generated binaries or the bundled catalogue. Third-party font notices are in `THIRD_PARTY_NOTICES.md`.
