# Contributing

## Setup

You need Python 3.13+ and [uv](https://docs.astral.sh/uv/). The dev tools (pytest, pytest-xdist, ruff and
[prek](https://prek.j178.dev/)) are uv dev dependencies, so `uv sync` installs them all into `.venv`:

```bash
uv sync                 # .venv with pygame-ce and the dev tools
uv run prek install     # the git hook: lint every commit
uv run main.py          # play
```

`prek` runs the hooks in `.pre-commit-config.yaml`; if you already use
[pre-commit](https://pre-commit.com/), `pre-commit install` reads the same file.

## Before a commit

1. **Lint**: the hook runs `ruff check --fix` on the files you commit. If it fixes something, the commit
   stops so you can look at the changes and stage them; if something can't be fixed automatically, fix it
   by hand. To run the hook on everything: `uv run prek run --all-files`.
2. **Test**: while working, run the tests that cover your change (below); before a commit, run the whole
   suite with `uv run pytest` (about 20 s, in parallel). See [TESTING.md](TESTING.md) for more ways to run it.
3. **Snapshots**: after an intended visual change, re-record the pixel snapshots and commit
   `tests/snapshots.json` ([TESTING.md](TESTING.md#pixel-snapshots)).

## Linting

```bash
uv run ruff check .          # what the hook checks, on every file
uv run ruff check . --fix    # and fix what it safely can
```

The rules are under `[tool.ruff]` in `pyproject.toml`: pyflakes, pycodestyle, import order, bugbear,
bandit (security), pyupgrade, comprehensions, simplifications, performance and pylint's errors and
warnings, at 120 columns. The ignored rules each say why. When a rule is wrong for one line, silence it
there with the reason: `# noqa: PLW0603 - one module-wide scale`.

ruff's version is pinned twice, as a dev dependency and as the hook's `rev:` in `.pre-commit-config.yaml`
(new ruff versions add rules); bump both together.

## Running the tests a change touches

`tools/select_tests.py` looks at what changed (with git) and picks the test files that cover it, so a
soundtrack change doesn't rerun the rendering snapshots or the long balance playthroughs:

```bash
uv run tools/select_tests.py                  # show the pick for what changed since the last commit
uv run tools/select_tests.py --run            # ... and run it
uv run tools/select_tests.py --base main --run   # include what was committed since the branch left main
uv run tools/select_tests.py music.py --run   # pick for these files instead of asking git
uv run tools/select_tests.py --run -- -x -q   # pytest's own options go after --
```

The map from files to tests is `RULES` at the top of the script. A changed test file runs itself; a
file no rule covers runs every test (as do `main.py`, `tests/helpers.py`, `tests/conftest.py` and the
project files), so the pick errs on the side of running more. The playthroughs (`slow`) only run for
changes to the rules and balance: towers, monsters, levels, waves, entities, the Monsters side.

## Adding a module or data file

- Give it a rule in `RULES` in `tools/select_tests.py` (`test_select_tests.py` fails until you do).
- Add a row for it to the project layout in [README.md](README.md#project-layout).
- A new test file goes in the table in [TESTING.md](TESTING.md#what-the-tests-cover).

## Writing tests

- Put the test in the file for its area (see the table in [TESTING.md](TESTING.md#what-the-tests-cover)), or a
  new `test_<area>.py`.
- Use the `game` fixture and the helpers in `tests/helpers.py` rather than building state by
  hand, and prefer sending events over calling internals when testing controls.
- Mark anything that takes more than a second or two with `@pytest.mark.slow`.
- Never write to the repo; use pytest's `tmp_path` fixture for files.
