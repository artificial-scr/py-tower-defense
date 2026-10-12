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
| `test_controls.py`, `test_launch.py` | Input and the game loop: keys, clicks at every display scale, the settings screen (scale, fullscreen, ambient effects), game speed only in waves, saved settings, quitting |
| `test_progress.py` | Moving between levels: the wave lock after a level change, Rebuild, the saved checkpoint and Continue |
| `test_runs.py` | Runs: passes that switch sides after the last level, finales (a Towers pass ending on the wave the Monsters pass was won, with the Warden), the run ending on a loss, picking a side, saving and continuing a run |
| `test_records.py` | Comps per wave, tower records (only stronger slots replace), the profile file, and the Towers side playing monster records (replayed abilities included) |
| `test_monsters.py` | Loading `monsters.json` and its error messages; monster mechanics (armor, healing, splitting, phasing, buffs) and abilities |
| `test_attack.py` | The Monsters side: the defender from a record, budget and share, drafting, abilities, lives that last the pass (clearing, winning and losing), stat upgrades and escorts, the starter pack, drawing |
| `test_unlocks.py` | `unlocks.json`, drawing and picking cards after wins (record tiers, sure rares), milestones, and what each tower card does |
| `test_balance_log.py` | The per-level balance logs: file names, uniqueness, and cross-checks that their numbers add up |
| `test_rendering.py` | Drawing: every screen at every display scale, text staying inside the map and panel, map decoration, tower sprites, every creature's animation frames, shots and hit effects, ambient particles, the portal and gate, plus pixel snapshots |
| `test_playthrough.py` | Long simulations with bot players, on both sides (marked `slow`) |

Most tests drive the game the way a player would, by sending pygame events to `Game`, and the
helpers for that (clicks, drags, placing towers, the bot players) are in `tests/helpers.py`.

## Test environment

`tests/conftest.py` sets this up for every test, so tests are independent of each other and of
your machine:

- **Headless**: SDL's dummy video and audio drivers are used, so no window opens and the tests
  run without a display (over SSH, in CI).
- **No writes to the repo**: `settings.json`, `savegame.json`, `profile.json` and the `logs/`
  folder are redirected to a temporary directory per test.
- **Starter pack already taken**: the temporary `profile.json` starts with the Monsters side's
  one-time starter cards marked as picked, so they don't cover every Monsters-side test. Tests of
  the starter pack overwrite the profile.
- **Reset state**: the display scale goes back to 100% and the random seed is fixed before each
  test, so runs are repeatable.

Useful fixtures: `game` (a fresh game at level 1, logging off), `logged_game` (writes balance
logs to the temporary directory), `screen`, and `mouse` (set the mouse position with
`mouse[:] = x, y`, in screen pixels). For the Monsters side, build a game with
`main.Game(screen, log_dir=None, side="monsters")`, or use the `attack` fixture in `test_attack.py`
(level 1 against a small two-wave tower record). Games in one test share the temporary
`profile.json`, so records and unlocks set by one game are seen by the next.

## Slow tests and balance

The tests marked `slow` play the game with a simple bot (buy towers on the best spots, fuse
whatever can fuse, pick branches at random). Besides checking that long games run without
errors, they act as a rough balance check: if a change to `towers.json` or the enemies makes the
game noticeably harder or easier, they are likely to start failing. Outcomes depend on the
random seed, so these tests pin their seeds; a failure after a balance change says the game
changed difficulty, not necessarily that something is broken.

On the Monsters side, the bot first sets tower records for levels 1 and 2, then scripted drafts
(`scripted_attack` in `tests/helpers.py`) attack them with no unlocks. They pin two properties of
the current balance:

- **Monsters level 1 stays winnable.** Even waves take enough lives to clear it, and one big push
  takes all 20, which wins the whole pass (there's no cap on lives per level). This matters more
  than it looks: monster cards only come from Monsters wins, so an unwinnable first level would be
  a dead end.
- **How you spend matters**: level 2 (whose record ends on Dragon + Absolute Zero) holds against one
  big push but not against evenly paced waves.

If a change to `monsters.json` or `towers.json` breaks these, look at the budget rules in
`monsters.json` first.

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
