"""Pick the test files that cover what changed, so a soundtrack change doesn't rerun the rendering
snapshots or the long balance playthroughs.

    uv run tools/select_tests.py                 # what changed since the last commit (untracked files too)
    uv run tools/select_tests.py --base main     # ... and since the branch left main
    uv run tools/select_tests.py music.py ...    # these files, instead of asking git
    uv run tools/select_tests.py --run [-- PYTEST ARGS]   # run the pick with pytest

Each changed file is matched against RULES (every rule that matches adds its tests). A file no rule
matches runs every test, so a new module is safe until it gets its own rule. A changed test file
runs itself.
"""

import argparse
import fnmatch
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALL = "ALL"
SHOWN = 4  # changed files listed per line of the report

# Tests that draw the game's screens: what a change to drawing code can break.
DRAWS = ("rendering", "runs", "unlocks", "tower_unlocks", "attack")
# The long bot playthroughs (marked slow): only for changes to the rules or the balance.
BALANCE = ("playthrough",)

# (file patterns, test files without "tests/test_" and ".py", or ALL); paths are relative to the repo root
RULES = [
    # everything runs through these
    (("main.py", "pyproject.toml", "uv.lock", "tests/conftest.py", "tests/helpers.py"), ALL),
    # game rules and balance
    (("towers.py", "towers.json", "evolution.json"),
     ("data", "fusion", "combat", "records", "unlocks", "tower_unlocks", "rendering") + BALANCE),
    (("monsters.py", "monsters.json"),
     ("monsters", "data", "combat", "attack", "records", "unlocks", "balance_log", "rendering") + BALANCE),
    (("levels.py",), ("data", "progress", "runs", "attack", "monsters", "rendering") + BALANCE),
    (("entities.py",),
     ("combat", "monsters", "fusion", "attack", "records", "tower_unlocks", "rendering") + BALANCE),
    (("attack.py",), ("attack", "runs", "records", "unlocks") + BALANCE),
    (("progress.py", "unlocks.json"), ("unlocks", "records", "runs", "progress", "attack", "tower_unlocks")),
    (("achievements.py", "achievements.json"), ("tower_unlocks", "unlocks")),
    (("balance_log.py",), ("balance_log",)),
    # drawing
    (("graphics.py",), DRAWS + ("controls", "launch", "progress", "music")),
    (("sprites.py", "terrain.py", "ambience.py", "assets/fonts/*"), DRAWS),
    (("effects.py",), ("combat", "monsters", "records", "rendering")),
    (("unlock_view.py",), ("tower_unlocks", "unlocks", "rendering")),
    (("attack_view.py",), ("attack", "rendering")),
    (("tests/snapshots.json",), ("rendering",)),
    # the soundtrack
    (("music.py", "music.json", "assets/music/*"), ("music", "launch")),
    # this script
    (("tools/select_tests.py",), ("select_tests",)),
    # nothing to test
    (("*.md", ".gitignore", ".gitattributes", ".serena/*", "logs/*", "tools/sync_music.py", "reset_profile.py"), ()),
]


def tests_for(path):
    """The test files (tests/test_*.py) covering a changed file, or ALL."""
    if fnmatch.fnmatch(path, "tests/test_*.py"):
        return {path}
    found, matched = set(), False
    for patterns, tests in RULES:
        if any(fnmatch.fnmatch(path, p) for p in patterns):
            if tests == ALL:
                return ALL
            matched = True
            found |= {f"tests/test_{t}.py" for t in tests}
    return found if matched else ALL


def has_rule(path):
    return fnmatch.fnmatch(path, "tests/test_*.py") or any(fnmatch.fnmatch(path, p) for ps, _ in RULES for p in ps)


def select(paths):
    """(test files to run or ALL, {path: its tests or ALL}). Deleted test files aren't run."""
    why = {path: tests_for(path) for path in paths}
    if any(tests == ALL for tests in why.values()):
        return ALL, why
    tests = set().union(*why.values()) if why else set()
    return sorted(t for t in tests if os.path.exists(os.path.join(ROOT, t))), why


def describe(path, tests):
    if tests == ALL:
        return "every test" if has_rule(path) else "every test (no rule for this file)"
    return ", ".join(os.path.basename(t)[len("test_"):-len(".py")] for t in sorted(tests)) or "no tests"


def git(*args):
    out = subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout
    return [line for line in out.splitlines() if line]


def changed_files(base=None):
    """Files changed in the working tree and index since HEAD, untracked ones, and with `base` those
    committed since the branch left it."""
    files = git("diff", "--name-only", "HEAD") + git("ls-files", "--others", "--exclude-standard")
    if base:
        files += git("diff", "--name-only", f"{base}...HEAD")
    return sorted(set(files))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("files", nargs="*", help="changed files (default: ask git)")
    parser.add_argument("--base", help="also count what was committed since the branch left this ref")
    parser.add_argument("--run", action="store_true", help="run the selected tests with pytest")
    argv = sys.argv[1:]
    cut = argv.index("--") if "--" in argv else len(argv)
    args, pytest_args = parser.parse_args(argv[:cut]), argv[cut + 1:]
    paths = args.files or changed_files(args.base)
    selected, why = select(paths)
    groups = {}  # what a file runs -> the files that run it
    for path, tests in why.items():
        groups.setdefault(describe(path, tests), []).append(path)
    for label, files in groups.items():
        shown = ", ".join(files[:SHOWN]) + (f" (+{len(files) - SHOWN} more)" if len(files) > SHOWN else "")
        print(f"  {label}  <-  {shown}")
    if not selected:
        print("No tests to run." if paths else "Nothing changed: no tests to run.")
        return 0
    command = ["pytest"] + ([] if selected == ALL else selected) + pytest_args
    print("Run:", "uv run " + " ".join(command), flush=True)
    if args.run:
        return subprocess.run([sys.executable, "-m", *command], cwd=ROOT).returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
