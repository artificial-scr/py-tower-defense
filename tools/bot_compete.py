"""Play every bot profile (tests/bot.py) over a few seeds and compare: where each falls, the share of
Frost-based towers it ends levels with, and what it aims for, picks and keeps.

    uv run tools/bot_compete.py                     # every profile, seeds 0-5, plus the Gun line alone
    uv run tools/bot_compete.py damage tall --seeds 10
    uv run tools/bot_compete.py --locked            # the top profiles on a fresh profile, run after run
"""

import argparse
import json
import multiprocessing
import os
import random
import sys
import tempfile
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]
SHOWN = 6  # most common targets, branches and towers listed per profile
TOP = ("damage", "crowd", "single", "tall")  # the profiles that win the pass with every tower (--locked's default)
RUNS = 8  # --locked: runs on one fresh profile, until a pass is won


def play(job):
    """One game with nothing saved to the player's files: (job, the level it ended on, its state, the bot's stats),
    or with locked, (job, bot_runs' runs)."""
    profile, lines, seed, locked = job
    import pygame
    from bot import bot_play, bot_runs

    import graphics
    import main
    from towers import TOWERS
    tmp = tempfile.mkdtemp()
    main.SETTINGS_FILE, main.SAVE_FILE, main.PROFILE_FILE = (os.path.join(tmp, f) for f in
                                                             ("settings.json", "savegame.json", "profile.json"))
    owned = {} if locked else {"towers_unlocked": list(TOWERS)}  # as in the tests: every tower, or the start ones
    with open(main.PROFILE_FILE, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "milestones": {"starter_pack": True}, **owned}, f)
    pygame.init()
    screen = pygame.display.set_mode(graphics.window_size())
    random.seed(seed)
    game = main.Game(screen, log_dir=None)
    if locked:
        return job, bot_runs(game, RUNS, profile)
    stats = bot_play(game, profile=profile, lines=lines)
    return job, game.level_idx + 1, game.state, stats


def main():
    from bot import PROFILES, frost_share
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("profiles", nargs="*", help=f"default: all ({', '.join(PROFILES)})")
    parser.add_argument("--seeds", type=int, default=6)
    parser.add_argument("--locked", action="store_true", help="a fresh profile: only the start towers owned")
    args = parser.parse_args()
    entries = [(p, None) for p in args.profiles or (TOP if args.locked else PROFILES)]
    if not args.profiles and not args.locked:
        entries.append(("damage", ("gun",)))
    jobs = [(p, lines, s, args.locked) for p, lines in entries for s in range(args.seeds)]
    results = {}
    with multiprocessing.Pool(min(len(jobs), os.cpu_count()), maxtasksperchild=1) as pool:
        for job, *result in pool.imap_unordered(play, jobs):
            results[job[:3]] = result
    if args.locked:
        for p, lines in entries:
            print(p)
            for s in range(args.seeds):
                runs, = results[(p, lines, s)]
                print(f"    seed {s}:", " | ".join(f"{end} {','.join(kinds) or '-'}" for end, kinds in runs))
        return
    for p, lines in entries:
        runs = [results[(p, lines, s)] for s in range(args.seeds)]
        ends = ["won" if state == "victory" else level for level, state, _ in runs]
        merged = {"levels": [lv for *_, st in runs for lv in st["levels"]]}
        targets, branches, kept = Counter(), Counter(), Counter()
        for *_, st in runs:
            targets += st["targets"]
            branches += Counter(chosen for _, chosen in st["branches"])
            kept += Counter(k for lv in st["levels"] for k in lv["towers"])
        print(f"{p + ('/' + ','.join(lines) if lines else ''):12} ends {ends}   Frost-based {frost_share(merged):.0%}")
        print("    aims for ", targets.most_common(SHOWN))
        print("    branches ", branches.most_common(SHOWN))
        print("    keeps    ", kept.most_common(SHOWN))


if __name__ == "__main__":
    main()
