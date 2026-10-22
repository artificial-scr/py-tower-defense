"""The bot player of the long simulations (test_playthrough.py, the balance-log tests) and of balance runs.

A planning bot: right after every purchase (and at the start of a level) it picks a target, a tower one
purchase and any number of fusions away, up to the finals, and the tier 1 tower to buy next toward it. Then it
waits for the gold, buys, fuses what its plan (or a gain in score) calls for, and plans again. A tower goes
on the free tile covering the most path for the range of the target it's bought for. When a fusion offers two
branches it picks one at random, weighted by the square of each branch's score.

How it scores a comp (a list of (kind, tile)) and picks its target is its profile (PROFILES):
  damage  most gain per gold in damage on the path: each tower's DPS (analytics/tower_stats.py, monsters
          at the usual wave spacing, every hit capped at the coming wave's average monster hp, as overkill
          is wasted) x the px of path in its range, a slowing tower stretching the time monsters spend on
          the stretch it covers by its slow, for the share of monsters it keeps slowed
  crowd   the same against a swarm (Swarmling spacing): splash, multishot and chains count for more
  single  the same against lone monsters: big hits count for more, splash for nothing
  dps     most gain per gold in DPS alone: no range, no slowing
  tall    the most damage gain, whatever it costs: saves for the strongest tower it can plan
  wide    most gain per gold, but only towers at most one fusion away (tiers 1-2)
  random  any target, picked at random (fusions and branches as damage)
  cycle   the bot before the planner: buys Gun, Cannon, Frost, Gun in turn on the spots covering the most
          path within 110 px, fuses whatever can fuse, picks branches at random

`lines` keeps a profile to some tower lines (("gun",): Guns and what they fuse into).
"""

import os
import random
import sys
from collections import Counter

from helpers import mouse_down, px

from levels import COLS, ROWS, TILE, tile_center
from monsters import ENEMY_TYPES
from towers import CROSS, LINES, TOWER_LINES, TOWERS, fusion_options

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "analytics"))
import tower_stats

PROFILES = {
    "damage": {"spacing": "wave", "pick": "per_gold"},
    "crowd": {"spacing": "swarm", "pick": "per_gold"},
    "single": {"spacing": "1 target", "pick": "per_gold"},
    "dps": {"spacing": "wave", "pick": "per_gold", "path": False},
    "tall": {"spacing": "wave", "pick": "gain"},
    "wide": {"spacing": "wave", "pick": "per_gold", "max_tier": 2},
    "random": {"spacing": "wave", "pick": "random"},
    "cycle": {"spacing": "wave", "cycle": ("gun", "cannon", "frost", "gun")},
}
CYCLE_RANGE = 110  # the cycle bot ranks spots by the path within a Gun's range, whatever it buys

# kind -> the two towers fused to make it (two of the same up to tier 3, a final's two tier 3 parents)
PARENTS = {}
for _t1, _t2, _branches in LINES.values():
    PARENTS[_t2] = (_t1, _t1)
    for _b in _branches:
        PARENTS[_b] = (_t2, _t2)
for _pair, _final in CROSS.items():
    PARENTS[_final] = tuple(sorted(_pair, key=list(TOWERS).index))


def parts(kind):
    """`kind` and every tower fused on the way to it."""
    return {kind}.union(*(parts(p) for p in PARENTS.get(kind, ())))


def frost_based(kind):
    return "frost" in TOWER_LINES[kind]


class Bot:
    def __init__(self, game, profile="damage", lines=None):
        self.game = game
        self.name = profile
        self.prefs = {"path": True, "max_tier": 4, **PROFILES[profile]}
        self.spacing = tower_stats.SPACINGS[self.prefs["spacing"]]
        self.lines = tuple(lines or LINES)
        self.dps = {}
        # what it did, for balance runs: purchases, targets, branch picks, and the towers at each level's end
        self.stats = {"bought": Counter(), "targets": Counter(), "branches": [], "levels": [], "unlocked": []}
        self.new_level()

    # ---- the map ---------------------------------------------------------------------------
    def new_level(self):
        self.cells = [tile_center(*c) for c in self.game.path_cells]
        self.cover = {}  # (tile, range) -> indices of the path cells in range
        self.ranked = {}  # range -> every tile not on the path, the most path covered first
        self.target = self.next_kind = None
        self.bought = 0  # this level (the cycle bot starts its cycle again)
        self.dirty = True  # plan (after any fusions) before buying

    def covered(self, tile, rng):
        key = (tile, rng)
        if key not in self.cover:
            c = tile_center(*tile)
            self.cover[key] = frozenset(i for i, p in enumerate(self.cells) if p.distance_to(c) <= rng)
        return self.cover[key]

    def best_free(self, rng):
        """The free tile covering the most path within `rng`, or None."""
        if rng not in self.ranked:
            tiles = [(x, y) for x in range(COLS) for y in range(ROWS) if (x, y) not in self.game.path_cells]
            self.ranked[rng] = sorted(tiles, key=lambda t: -len(self.covered(t, rng)))
        return next((t for t in self.ranked[rng] if self.game.is_free(t)), None)

    # ---- the score ------------------------------------------------------------------------
    def monster_hp(self):
        """The hp of the coming wave's average monster (bosses left out): what one hit can take at most."""
        g = self.game
        if g.wave_idx < g.level_waves:
            _, wave = g.next_wave()
            kinds, hp_mult = wave.kinds, wave.hp_mult
        else:
            kinds, hp_mult = g.spawn_queue or ["basic"], g.hp_mult
        hps = [ENEMY_TYPES[k]["hp"] for k in kinds if "boss" not in ENEMY_TYPES[k]] or [ENEMY_TYPES["basic"]["hp"]]
        return sum(hps) / len(hps) * hp_mult

    def update_dps(self):
        """Each tower's DPS (tower_stats.dps, at the profile's spacing) with every hit capped at monster_hp:
        overkill is wasted, so a Sniper's 160 damage counts for little against 55 hp monsters."""
        hp = self.monster_hp()
        for kind, spec in TOWERS.items():
            weights, burnt = tower_stats.victims(spec, self.spacing)
            hit = tower_stats.hit_damage(spec)
            self.dps[kind] = (spec["rate"] * sum(min(hit * w, hp) for w in weights)
                              + tower_stats.burn_dps(spec) * burnt)

    def stretch(self, spec, tile):
        """How much longer a monster takes over the path a slowing tower covers: 1 / slow for the share of
        monsters it keeps slowed (shots x targets per shot x slow time, over the monsters in its range)."""
        cells = self.covered(tile, spec["range"])
        in_range = max(1.0, len(cells) * TILE / self.spacing)
        targets = tower_stats.victims(spec, self.spacing)[1]
        slowed = min(1.0, spec["rate"] * targets * spec["slow_time"] / in_range)
        return 1 + slowed * (1 / spec["slow"] - 1)

    def score(self, comp):
        """The profile's score of towers (kind, tile): damage on the path, or DPS alone."""
        if not self.prefs["path"]:
            return sum(self.dps[k] for k, _ in comp)
        stretch = [1.0] * len(self.cells)
        for kind, tile in comp:
            spec = TOWERS[kind]
            if "slow" in spec:
                f = self.stretch(spec, tile)
                for i in self.covered(tile, spec["range"]):
                    stretch[i] = max(stretch[i], f)
        return sum(self.dps[k] * TILE * sum(stretch[i] for i in self.covered(t, TOWERS[k]["range"]))
                   for k, t in comp)

    # ---- planning ---------------------------------------------------------------------------
    def allowed(self, kind):
        """Whether the profile may aim for `kind`: within its tier and lines, and every part can be made."""
        return (TOWERS[kind]["tier"] <= self.prefs["max_tier"]
                and all(self.game.can_make(p) and (TOWERS[p]["tier"] > 1 or TOWERS[p]["line"] in self.lines)
                        for p in parts(kind)))

    def recipe(self, kind, pool, top=True):
        """(towers from `pool` it uses, tier 1 towers to buy) to make `kind`: towers already on the map are
        used where they fit (not as the target itself), parts are bought for the rest. Takes from pool."""
        if not top:
            have = next((t for t in pool if t.kind == kind), None)
            if have:
                pool.remove(have)
                return [have], []
        if TOWERS[kind]["tier"] == 1:
            return [], [kind]
        used, buy = [], []
        for p in PARENTS[kind]:
            u, b = self.recipe(p, pool, False)
            used, buy = used + u, buy + b
        return used, buy

    def options(self):
        """(target, tier 1 towers to buy for it, their cost, the score it adds) for every target in reach."""
        towers = list(self.game.towers.values())
        now = [(t.kind, t.tile) for t in towers]
        base = self.score(now)
        found = []
        for kind in TOWERS:
            if not self.allowed(kind):
                continue
            used, buy = self.recipe(kind, list(towers))
            if not buy:
                continue  # fusions alone: fuse_once's business
            rng = TOWERS[kind]["range"]
            tiles = [t.tile for t in used] + [t for t in [self.best_free(rng)] if t]
            if not tiles:
                continue
            tile = max(tiles, key=lambda t: len(self.covered(t, rng)))
            after = [(t.kind, t.tile) for t in towers if t not in used] + [(kind, tile)]
            found.append((kind, buy, sum(TOWERS[k]["cost"] for k in buy), self.score(after) - base))
        return found

    def plan(self):
        """Pick the target and the tier 1 tower to buy next for it."""
        self.target = self.next_kind = None
        if "cycle" in self.prefs:
            kinds = [k for k in self.prefs["cycle"] if TOWERS[k]["line"] in self.lines] or [self.lines[0]]
            self.target = self.next_kind = kinds[self.bought % len(kinds)]
            return
        found = self.options()
        if not found:
            return
        pick = self.prefs["pick"]
        if pick == "random":
            choice = random.choice(found)
        elif pick == "gain":
            choice = max(found, key=lambda o: (o[3], -o[2]))
        else:
            choice = max(found, key=lambda o: o[3] / o[2])
        self.target, self.next_kind = choice[0], choice[1][0]
        self.stats["targets"][self.target] += 1

    # ---- acting ------------------------------------------------------------------------------
    def fuse_once(self):
        """Fuse one pair the plan calls for, or that adds to the score (the cycle bot: any pair). The piece
        on the tile covering less path for the result's range goes onto the other. Returns whether it fused."""
        g = self.game
        towers = list(g.towers.values())
        planned = parts(self.target) if self.target else set()
        now = [(t.kind, t.tile) for t in towers]
        base = None
        for i, a in enumerate(towers):
            for b in towers[i + 1:]:
                made = [k for k in fusion_options(a.kind, b.kind) if g.can_make(k)]
                if not made:
                    continue
                rng = CYCLE_RANGE if "cycle" in self.prefs else max(TOWERS[k]["range"] for k in made)
                keep, drop = sorted((a, b), key=lambda t: -len(self.covered(t.tile, rng)))
                if "cycle" not in self.prefs and not planned & set(made):
                    base = self.score(now) if base is None else base
                    rest = [(t.kind, t.tile) for t in towers if t is not a and t is not b]
                    if max(self.score(rest + [(k, keep.tile)]) for k in made) <= base:
                        continue
                g.dragging = drop
                g.drop_dragged(px(keep.tile))
                return True
        return False

    def choose(self):
        """Pick a branch: at random, weighted by the square of each branch's score (the cycle bot: 50/50)."""
        g = self.game
        tower, options = g.choice
        ok = [i for i, k in enumerate(options) if g.can_make(k)]
        if "cycle" in self.prefs:
            index = random.randrange(2)
        else:
            rest = [(t.kind, t.tile) for t in g.towers.values() if t is not tower]
            base = self.score(rest)
            weights = [max(0.0, self.score(rest + [(options[i], tower.tile)]) - base) ** 2 for i in ok]
            index = random.choices(ok, weights=weights)[0] if sum(weights) else random.choice(ok)
        if index in ok:
            self.stats["branches"].append((tuple(options), options[index]))
        g.choose(index)

    def buy(self):
        g = self.game
        kind = self.next_kind
        rng = CYCLE_RANGE if "cycle" in self.prefs else TOWERS[self.target]["range"]
        tile = self.best_free(rng)
        if tile:
            g.build_kind = kind
            g.handle_event(mouse_down(px(tile)))
            g.build_kind = None
        if tile and g.towers.get(tile) and g.towers[tile].kind == kind:
            self.bought += 1
            self.stats["bought"][kind] += 1
        self.dirty = True

    def step(self):
        """One frame's decisions."""
        g = self.game
        if not self.dps:
            self.update_dps()
        if g.pending_unlocks:  # a tower unlocked (a profile that doesn't own them all): put its card away, plan again
            self.stats["unlocked"].append((g.level_idx + 1, g.pending_unlocks[0]["kind"]))
            g.dismiss_unlock()
            self.dirty = True
            return
        if g.choice:
            self.choose()
            return
        if self.dirty:
            self.update_dps()
            if self.fuse_once():
                return
            self.plan()
            self.dirty = False
        if self.next_kind and g.gold >= TOWERS[self.next_kind]["cost"]:
            self.buy()

    def level_done(self):
        kinds = [t.kind for t in self.game.towers.values()]
        self.stats["levels"].append({"level": self.game.level_idx + 1, "lives": self.game.lives, "towers": kinds,
                                     "frost_based": sum(map(frost_based, kinds))})


def bot_play(game, until_level=None, max_frames=3_000_000, move_and_sell=False, profile="damage", lines=None):
    """Play with a Bot until the game is won or lost, or level `until_level` (1-based) is reached.
    With move_and_sell, it also moves one tower mid-wave and sells one per level. Returns the bot's stats."""
    bot = Bot(game, profile, lines)
    sold, moved, level_frame = False, False, 0
    for _ in range(max_frames):
        level_frame += 1
        if game.state in ("game_over", "victory"):
            if game.state == "victory":
                bot.level_done()
            return bot.stats
        if game.state == "level_complete":
            bot.level_done()
            game.advance()
            bot.new_level()
            sold, moved, level_frame = False, False, 0
            if until_level and game.level_idx + 1 >= until_level:
                return bot.stats
            continue
        bot.step()
        if move_and_sell and level_frame >= 600 and not moved and game.state == "wave" and game.towers:
            t = next(iter(game.towers.values()))
            game.dragging = t
            game.drop_dragged(px(bot.best_free(TOWERS[t.kind]["range"])))
            moved = True
        pieces = [t for t in game.towers.values() if TOWERS[t.kind]["tier"] == 1]
        if move_and_sell and level_frame >= 900 and not sold and pieces:
            game.selected = pieces[-1]  # a piece bought toward a target, not what holds the line
            game.sell_selected()
            sold = True
            bot.dirty = True  # plan again with the refund
        if game.state == "build":
            game.start_wave()
        game.update(1 / 60)
    raise AssertionError(f"bot still playing after {max_frames} frames")


def bot_runs(game, max_runs, profile="damage"):
    """Play runs on the game's profile, its unlocks carrying over, until a Towers pass is won or `max_runs`
    are played. Returns each run's end (the level it fell on, or "won") and the towers unlocked in it."""
    runs = []
    for _ in range(max_runs):
        stats = bot_play(game, profile=profile)
        runs.append(("won" if game.state == "victory" else game.level_idx + 1, [k for _, k in stats["unlocked"]]))
        if game.state == "victory":
            break
        game.new_run("towers")
    return runs


def frost_share(stats):
    """Share of the towers on the map at the end of levels that are Frost-based (Frost line or a final with it)."""
    towers = sum(len(lv["towers"]) for lv in stats["levels"])
    return sum(lv["frost_based"] for lv in stats["levels"]) / towers if towers else 0.0
