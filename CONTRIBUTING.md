# Contributing to SUPERASTRA

## Local setup

Use Python 3.10 or newer. The desktop UI requires Tkinter; runtime Python packages
are not needed. Keep the source tree together because the Lua bridge and image
assets are loaded relative to the project root.

```sh
python -m venv .venv
```

Activate it with `.venv\Scripts\activate` on Windows or
`source .venv/bin/activate` on Linux, then run:

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python run.py
```

The automated suite uses an actual Lua runtime with emulator fixtures and a
simulated API transport. It does not require a ROM, running emulator or API key.
For live checks, see [validation notes](docs/VALIDATION.md). Describe what you
actually verified when submitting changes, especially for unfamiliar games.

## Project layout

- `astra_snes/`: desktop UI, model agent, memory tools and bridge transport.
- `emulator/`: BizHawk adapter, Lua execution engine and local SMW shortcuts.
- `profiles/`: optional memory maps for exact cartridge versions.
- `assets/`: UI logos and source credits.
- `tests/`: automated fixtures and optional live-game harness.
- `docs/`: architecture, changelog and validation evidence.

Preserve expected-byte guards, session/ROM checks, mutation rollback and Undo
when changing memory operations. Update the relevant tests for behavioral changes.
For UI changes, check the 920×920 default and 800×840 minimum window sizes.

## Preparing a release

Update `astra_snes/__init__.py`, the README version and `docs/CHANGELOG.md`.
Run the test suite above, then build a clean source archive:

```sh
python scripts/package_release.py
```

The ZIP is written to `dist/`. The builder includes only the maintained source,
documentation, tests and assets; local bridge data, notebooks, ROMs and virtual
environments are excluded. The app recreates its local data folders when started.

Before a GitHub push, review `git status --short` and `git diff --cached`.
Do not stage API keys, ROM files, emulator saves, or local `ipc/` and `knowledge/`
contents. Existing ignored files can still be tracked if explicitly forced into
Git, so review the staged file list. No account or repository URL is baked into
this project.

The source is MIT-licensed. Preserve the bundled JSON library license and the
separate Spellbook logo credit in `assets/README.md`.
