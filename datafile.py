"""Reading and writing the game's JSON files.

The shipped data files (towers.json, monsters.json, ...) are read once, at import, and checked as they load: a
mistake stops the game with a message naming the file, the entry and the problem (fail, check_fields). The
player's own files (settings, the save, the profile) are optional: read_json_or falls back to a default, and
write_json_atomic never leaves half a file behind.
"""

import json
import os


def read_json(path):
    with open(path, encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as err:
            raise ValueError(f"{os.path.basename(path)}: {err}") from None


def fail(path, *parts):
    """Stop loading a data file, with "<file>: <part>: ...: <problem>"."""
    raise ValueError(": ".join((os.path.basename(path), *parts)))


def check_fields(path, what, raw, required, extras=()):
    """Fail unless `raw` has every required field, and no field that's neither required nor an extra."""
    missing = [f for f in required if f not in raw]
    unknown = [f for f in raw if f not in required and f not in extras]
    if missing or unknown:
        fail(path, what, f"missing fields {missing}" if missing else f"unknown fields {unknown}")


def read_json_or(path, default, warn=None):
    """The JSON in `path`, or `default` if it's missing or unreadable (saying so after `warn`, if given)."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as err:
        if warn:
            print(f"{warn}: {err}")
        return default


def write_json_atomic(path, data):
    """Write `data` to `path` through a temporary file, so a crash never leaves a half-written file behind.
    Raises OSError if it can't."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)
