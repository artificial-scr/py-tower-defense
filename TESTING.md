# Testing

The tests live in `tests/` and use [pytest](https://docs.pytest.org/), installed as a uv dev
dependency. Run them through uv so they use the project's environment (`.venv`):

```bash
uv run pytest
```

Plain `python3 -m pytest` only works if pytest and pygame-ce are installed in that interpreter.

## Running a subset

```bash
uv run pytest -m "not slow"              # skip the long simulations (seconds instead of ~40 s)
uv run pytest -m slow                    # only the long simulations
uv run pytest tests/test_combat.py       # one file
uv run pytest -k boss                    # tests whose name matches an expression
uv run pytest -x                         # stop at the first failure
uv run pytest -rs                        # show why tests were skipped
uv run pytest --durations=10             # list the slowest tests
```

## What the tests cover

| Files | Area |
|---|---|
| `test_data.py` | Loading `towers.json` and `evolution.json`, the error messages for broken files, the level paths and wave generation |
| `test_fusion.py`, `test_combat.py` | Game rules: buying, fusing, moving and selling towers; tower mechanics; enemies and bosses |
| `test_controls.py`, `test_launch.py` | Input and the game loop: keys, clicks at every display scale, the settings screen, saved settings, quitting |
| `test_progress.py` | Moving between levels: the wave lock after a level change, Rebuild, the saved checkpoint and Continue |
| `test_balance_log.py` | The per-level balance logs: file names, uniqueness, and cross-checks that their numbers add up |
| `test_rendering.py` | Drawing: every screen at every display scale, plus pixel snapshots |
| `test_playthrough.py` | Long simulations with a bot player (marked `slow`) |

Most tests drive the game the way a player would, by sending pygame events to `Game`, and the
helpers for that (clicks, drags, placing towers, the bot player) are in `tests/helpers.py`.

## Test environment

`tests/conftest.py` sets this up for every test, so tests are independent of each other and of
your machine:

- **Headless**: SDL's dummy video and audio drivers are used, so no window opens and the tests
  run without a display (over SSH, in CI).
- **No writes to the repo**: `settings.json`, `savegame.json` and the `logs/` folder are
  redirected to a temporary directory per test.
- **Reset state**: the display scale goes back to 100% and the random seed is fixed before each
  test, so runs are repeatable.

Useful fixtures: `game` (a fresh game at level 1, logging off), `logged_game` (writes balance
logs to the temporary directory), `screen`, and `mouse` (set the mouse position with
`mouse[:] = x, y`, in screen pixels).

## Slow tests and balance

The tests marked `slow` play the game with a simple bot (buy towers on the best spots, fuse
whatever can fuse, pick branches at random). Besides checking that long games run without
errors, they act as a rough balance check: if a change to `towers.json` or the enemies makes the
game noticeably harder or easier, they are likely to start failing. Outcomes depend on the
random seed, so these tests pin their seeds; a failure after a balance change says the game
changed difficulty, not necessarily that something is broken.

## Pixel snapshots

The snapshot test in `test_rendering.py` draws a fixed set of screens at two scales and compares
a hash of each one with `tests/snapshots.json`. Any visual change, even a single pixel, makes it
fail. This is what catches unintended changes during refactors.

After an intended visual change, record new snapshots and commit `tests/snapshots.json`:

```bash
UPDATE_SNAPSHOTS=1 uv run pytest tests/test_rendering.py
```

Text renders slightly differently between pygame-ce versions, so the file records the version it
was made with, and the snapshot test is skipped (not failed) under any other version. Re-record
the snapshots after upgrading pygame-ce.

## Writing new tests

- Put the test in the file for its area (see the table above), or a new `test_<area>.py`.
- Use the `game` fixture and the helpers in `tests/helpers.py` rather than building state by
  hand, and prefer sending events over calling internals when testing controls.
- Mark anything that takes more than a second or two with `@pytest.mark.slow`.
- Never write to the repo; use pytest's `tmp_path` fixture for files.
