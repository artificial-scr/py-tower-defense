"""Tower vs monster matchups, played out headless with the real combat rules (entities.py).

    uv run analytics/matchups.py                        # every checkpoint (several minutes, uses all cores)
    uv run analytics/matchups.py --checkpoint mid       # one checkpoint
    uv run analytics/matchups.py --csv out/             # the matrices as CSV too
    uv run analytics/matchups.py --counter-scores       # ... then the scores for waves.json's counters

Each cell: the tower gold it takes to stop 100 gold of one monster kind (lower = the tower counters it).
  - a comp is one tower kind, as many copies as a checkpoint's defender gold buys, placed one by one on the
    free tile covering the most path (as Rebuild does) on level 2's map, the one whose matchups came closest
    to the median of all ten maps (level 1's were among the furthest)
  - the wave is WAVE_SHARE of that gold in one monster kind, drafted (wave_hp_mult, the kind's own gap), no
    buffs, abilities or cards. A single kind streams in at a steady rate, so a comp either keeps up forever or
    falls after a few: counting the monsters it stops says little. Instead the search finds the most hp (as a
    multiple s of the checkpoint's) at which the comp lets none of the wave through, and the cell is
    100 x comp gold / (wave gold x s): the gold needed if what a comp holds grows with its gold
  - the frost line's slowing towers (Frost, Chiller, Blizzard) are support only: they're never a comp alone,
    but mixed into a same-tier tower's comp for a share of its gold, and judged on the gold that saves
    against that tower alone. In a mix the supports are placed first, apart, and the damage towers where
    they overlap the supports most (see place). Shatter and the tier 4 towers made from the frost line are
    comps of their own.
Then, per checkpoint: the counters to each monster, each comp's worst matchup, dominated comps and monsters,
the equilibrium of the zero-sum game (the tower player picks a comp, the monster player sees it and drafts),
and monster costs that would make every monster as hard to stop per gold. With --counter-scores, last, each
tower tag's scores for waves.json (see counter_scores).
The search assumes a comp that holds monsters of some hp holds weaker ones; that holds closely, not exactly.
"""

import argparse
import csv
import json
import math
import multiprocessing
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from entities import Enemy, Tower, heal_auras, sabotage, speed_auras  # noqa: E402
from levels import COLS, LAYOUTS, ROWS, build_path_cells, tile_center, wave_hp_mult  # noqa: E402
from monsters import ENEMY_TYPES  # noqa: E402
from tower_stats import percent, print_table, tower_gold  # noqa: E402
from towers import TOWERS  # noqa: E402
from waves import TAG_OF  # noqa: E402

# name -> (1-based level, 1-based wave, defender gold, tower tiers in play). The gold is about what the
# strongest comps in the balance logs were worth there.
CHECKPOINTS = {
    "early": (2, 3, 600, (1, 2, 3)),
    "mid": (5, 3, 2400, (2, 3, 4)),
    "late": (9, 3, 5000, (3, 4)),
}
SCORE_CAP = 4  # a cell more than this many times the median tower's counts as this (a '-' would be infinite)
SUPPORT_ONLY = ("frost", "chiller", "blizzard")
SUPPORT_SHARES = (0.25, 0.5)  # share of a mixed comp's gold put into its support towers
MAX_TOWERS = 40  # a comp never has more towers than this
WAVE_SHARE = 0.5  # wave gold / defender gold: a Monsters-side wave gets 40%+ of the comp's value, plus savings
HP_RANGE = (1 / 64, 64)  # the hp multiples s the search tries: past them a cell shows as '-' or capped ('<')
HP_STEPS = 8  # halvings of the search in log space: s to within ~3%
DT = 1 / 60  # the game's frame at 1x
MONSTERS = [k for k, s in ENEMY_TYPES.items() if s["draft"] in ("starter", "unlock")]
GOLD = tower_gold()
WAYPOINTS = LAYOUTS[1]
PATH_PTS = [tile_center(x, y) for x, y in WAYPOINTS]
PATH_CELLS = build_path_cells(WAYPOINTS)


# --------------------------------------------------------------------------
# Comps and placement
# --------------------------------------------------------------------------
def solo(kind, gold):
    """A comp of one tower kind for about `gold`: [(kind, count)]."""
    return [(kind, max(1, min(MAX_TOWERS, round(gold / GOLD[kind]))))]


def mixed(support, partner, gold, share):
    """`partner`'s comp with `share` of its gold moved into `support` towers."""
    n_support = max(1, round(share * gold / GOLD[support]))
    n_partner = max(1, round((gold - n_support * GOLD[support]) / GOLD[partner]))
    return [(support, n_support), (partner, n_partner)]


def comp_gold(comp):
    return sum(GOLD[kind] * n for kind, n in comp)


def comp_label(comp):
    """A solo comp's tower kind; a mixed one's kinds and the share of its gold in support."""
    if len(comp) == 1:
        return comp[0][0]
    return f"{'+'.join(kind for kind, _ in comp)} {GOLD[comp[0][0]] * comp[0][1] / comp_gold(comp):.0%}"


def place(comp):
    """[(kind, tile)]. The supports first, each on the free tile whose range covers the most path that no
    other support covers yet (the least overlap once none is left), so they slow different stretches. Then
    the other towers, most expensive first, each on the free tile whose range covers the most path inside
    the supports' ranges, then the most path. Without supports that's Game.rebuild's rule: the tile covering
    the most path (ties: the lowest tile)."""
    cells = [tile_center(*c) for c in PATH_CELLS]
    taken = set(PATH_CELLS)
    slowed = set()  # indexes of the path cells inside a support's range
    placed = []
    for kind, n in sorted(comp, key=lambda kn: (kn[0] not in SUPPORT_ONLY, -GOLD[kn[0]])):
        rng = TOWERS[kind]["range"]
        reach = {(x, y): {i for i, p in enumerate(cells) if p.distance_to(tile_center(x, y)) <= rng}
                 for x in range(COLS) for y in range(ROWS)}
        support = kind in SUPPORT_ONLY
        for _ in range(n):
            tile = max((t for t in reach if t not in taken),
                       key=lambda t: ((-1 if support else 1) * len(reach[t] & slowed), len(reach[t]), -t[0], -t[1]))
            taken.add(tile)
            placed.append((kind, tile))
            if support:
                slowed |= reach[tile]
    return placed


# --------------------------------------------------------------------------
# One wave, played out
# --------------------------------------------------------------------------
def leaks(placement, kind, count, hp_mult):
    """Whether any of `count` monsters of `kind` gets past the towers (the game's update loop, minus
    everything that only draws or keeps score). Stops at the first leak."""
    towers = [Tower(k, tile) for k, tile in placement]
    queue = count
    enemies, projectiles, effects = [], [], []
    spawn_timer = 0.0
    gap = ENEMY_TYPES[kind]["gap"]
    while queue or enemies:
        if queue:
            spawn_timer -= DT
            if spawn_timer <= 0:
                enemies.append(Enemy(kind, PATH_PTS, hp_mult))
                queue -= 1
                spawn_timer = gap
        for e in enemies:
            e.update(DT)
        heal_auras(enemies, DT)
        speed_auras(enemies)
        for caster in [e for e in enemies if e.alive and "decoy" in e.spec]:  # Game.cast_decoys
            caster.decoy_timer -= DT
            if caster.decoy_timer <= 0:
                caster.decoy_timer = caster.spec["decoy"][0]
                enemies.append(caster.cast_illusion())
        for t in towers:
            t.update(DT, enemies, projectiles, effects)
        for p in projectiles:
            p.update(DT, enemies, effects)
        projectiles = [p for p in projectiles if not p.done]
        effects.clear()
        alive = []
        for e in enemies:
            if e.alive:
                alive.append(e)
            elif e.illusion:
                continue
            elif e.escaped:
                return True  # a Looter takes no lives, but it brings budget back: it counts as a leak too
            else:
                if "sabotage" in e.spec:
                    sabotage(e, towers, effects)
                alive += e.split()
        enemies = alive
        if not queue and all(e.illusion for e in enemies):
            break
    return False


def wave_size(kind, gold):
    """Monsters of `kind` in a wave worth WAVE_SHARE of `gold` (at least one)."""
    return max(1, round(WAVE_SHARE * gold / ENEMY_TYPES[kind]["cost"]))


def toughest_held(comp, kind, hp_mult):
    """The largest multiple s of `hp_mult` at which the comp lets none of its wave of `kind` through
    (bisection in log space within HP_RANGE); 0 if it can't hold even the weakest, inf past the strongest."""
    placement = place(comp)
    count = wave_size(kind, comp_gold(comp))
    lo, hi = (math.log2(s) for s in HP_RANGE)
    if leaks(placement, kind, count, hp_mult * 2 ** lo):
        return 0.0
    if not leaks(placement, kind, count, hp_mult * 2 ** hi):
        return math.inf
    for _ in range(HP_STEPS):
        mid = (lo + hi) / 2
        if leaks(placement, kind, count, hp_mult * 2 ** mid):
            hi = mid
        else:
            lo = mid
    return 2 ** lo


def cell(comp, kind, hp_mult):
    """(tower gold per 100 monster gold, capped): inf when the comp can't hold the wave at the lowest hp
    tried; capped when it holds it at the highest, so the cell is at most the value shown."""
    held = toughest_held(comp, kind, hp_mult)
    gold = comp_gold(comp)
    wave_gold = wave_size(kind, gold) * ENEMY_TYPES[kind]["cost"]
    if held == 0:
        return math.inf, False
    if math.isinf(held):
        return 100 * gold / (wave_gold * HP_RANGE[1]), True
    return 100 * gold / (wave_gold * held), False


def run_cell(args):
    comp, kind, hp_mult = args
    return cell(comp, kind, hp_mult)


# --------------------------------------------------------------------------
# A checkpoint's matrix
# --------------------------------------------------------------------------
def comps_for(name):
    """(solo comps, {(support, partner, share): mixed comp}) for a checkpoint."""
    _, _, gold, tiers = CHECKPOINTS[name]
    kinds = [k for k, s in TOWERS.items() if s["tier"] in tiers]
    solos = [solo(k, gold) for k in kinds if k not in SUPPORT_ONLY]
    mixes = {}
    for s in [k for k in kinds if k in SUPPORT_ONLY]:
        for p in [k for k in kinds if k not in SUPPORT_ONLY and TOWERS[k]["tier"] == TOWERS[s]["tier"]]:
            for share in SUPPORT_SHARES:
                comp = mixed(s, p, gold, share)
                if comp not in mixes.values():  # with little gold, both shares can round to the same towers
                    mixes[(s, p, share)] = comp
    return solos, mixes


def matrix(name, monsters, jobs):
    """{comp label: {monster: (cell, capped)}}, the comps, and the mixed comps by (support, partner, share)."""
    level, wave, _, _ = CHECKPOINTS[name]
    hp_mult = wave_hp_mult(level - 1, wave - 1)
    solos, mixes = comps_for(name)
    comps = solos + list(mixes.values())
    tasks = [(comp, m, hp_mult) for comp in comps for m in monsters]
    with multiprocessing.Pool(jobs) as pool:
        results = pool.map(run_cell, tasks, chunksize=1)
    cells = {}
    for (comp, m, _), result in zip(tasks, results):
        cells.setdefault(comp_label(comp), {})[m] = result
    return cells, solos, mixes


def support_rows(cells, mixes, monsters):
    """Gold a support saves its partner: 1 - mixed comp's cell / partner alone's, per monster."""
    rows = []
    for (support, partner, share), comp in mixes.items():
        mix, alone = cells[comp_label(comp)], cells[partner]
        row = {"support": support, "partner": partner, "share": share, "label": comp_label(comp),
               "comp": " + ".join(f"{n} {k}" for k, n in comp)}
        for m in monsters:
            a, b = alone[m][0], mix[m][0]
            row[m] = (1 - b / a) if math.isfinite(a) and math.isfinite(b) else (1.0 if math.isfinite(b) else -math.inf)
        finite = [row[m] for m in monsters if math.isfinite(row[m])]
        row["mean"] = statistics.mean(finite) if finite else -math.inf
        rows.append(row)
    return rows


def best_mixes(support):
    """The labels of the mixed comps the matrix keeps: each (support, partner) pair's share that saves the
    most gold on average."""
    best = {}
    for row in support:
        key = (row["support"], row["partner"])
        if key not in best or row["mean"] > best[key]["mean"]:
            best[key] = row
    return [row["label"] for row in best.values()]


def stopped(value):
    """Monster gold a comp stops per 100 tower gold: the payoff the tower player wants high."""
    return 0.0 if math.isinf(value) else 100 * 100 / value


def geomean(values):
    values = [max(v, 1e-6) for v in values]
    return math.exp(statistics.mean(math.log(v) for v in values))


def counters(table, monsters):
    rows = []
    for m in monsters:
        col = sorted(((table[c][m], c) for c in table), key=lambda vc: vc[0])
        best, worst = col[0], col[-1]
        rows.append({"monster": m, "best": best[1], "best gold": best[0], "worst": worst[1],
                     "worst gold": worst[0], "spread": worst[0] / best[0] if math.isfinite(worst[0]) else math.inf})
    return rows


def worst_matchups(table, monsters):
    rows = []
    for c, row in table.items():
        worst = max(monsters, key=lambda m: row[m])
        median = statistics.median(row[m] for m in monsters)
        rows.append({"comp": c, "worst vs": worst, "gold": row[worst], "median": median,
                     "x median": row[worst] / median if math.isfinite(row[worst]) else math.inf})
    return sorted(rows, key=lambda r: -r["x median"])


def dominated(table, monsters):
    """Comps another comp beats against every monster, and monsters another monster beats against every
    comp (for the monster player: costs at least as much tower gold to stop per gold, everywhere)."""
    comps = list(table)
    lines = []
    for a in comps:
        by = [b for b in comps if b != a and all(table[b][m] <= table[a][m] for m in monsters)
              and any(table[b][m] < table[a][m] for m in monsters)]
        if by:
            lines.append(f"comp {a} is beaten everywhere by {', '.join(by)}")
    for a in monsters:
        by = [b for b in monsters if b != a and all(table[c][b] >= table[c][a] for c in comps)
              and any(table[c][b] > table[c][a] for c in comps)]
        if by:
            lines.append(f"monster {a} is beaten everywhere by {', '.join(by)}")
    return lines


def equilibrium(table, monsters, rounds=20000):
    """Mixed strategies of the zero-sum game, by multiplicative weights: payoff = monster gold stopped per
    100 tower gold. Returns (tower weights, monster weights, value)."""
    comps = list(table)
    pay = [[stopped(table[c][m]) for m in monsters] for c in comps]
    top = max(max(r) for r in pay) or 1.0
    eta = math.sqrt(8 * math.log(max(len(comps), len(monsters))) / rounds)
    wt, wm = [1.0] * len(comps), [1.0] * len(monsters)
    avg_t, avg_m = [0.0] * len(comps), [0.0] * len(monsters)
    for _ in range(rounds):
        st, sm = sum(wt), sum(wm)
        pt, pm = [w / st for w in wt], [w / sm for w in wm]
        for i, p in enumerate(pt):
            avg_t[i] += p
        for j, p in enumerate(pm):
            avg_m[j] += p
        gain_t = [sum(pay[i][j] * pm[j] for j in range(len(monsters))) / top for i in range(len(comps))]
        loss_m = [sum(pay[i][j] * pt[i] for i in range(len(comps))) / top for j in range(len(monsters))]
        wt = [w * math.exp(eta * g) for w, g in zip(wt, gain_t)]
        wm = [w * math.exp(-eta * g) for w, g in zip(wm, loss_m)]
        st, sm = max(wt), max(wm)
        wt, wm = [w / st for w in wt], [w / sm for w in wm]
    pt = {c: w / rounds for c, w in zip(comps, avg_t)}
    pm = {m: w / rounds for m, w in zip(monsters, avg_m)}
    value = sum(pt[c] * pm[m] * stopped(table[c][m]) for c in comps for m in monsters)
    return pt, pm, value


def fair_costs(table, monsters):
    """Each monster's cost scaled so every monster takes the same tower gold to stop per gold (geometric
    means over the comps): a monster that's easy to stop for its cost gets cheaper."""
    per = {m: geomean(stopped(table[c][m]) for c in table) for m in monsters}
    overall = geomean(per.values())
    return [{"monster": m, "cost": ENEMY_TYPES[m]["cost"], "stopped/100g": per[m],
             "fair cost": ENEMY_TYPES[m]["cost"] * overall / per[m]} for m in monsters]


def counter_scores(tables, monsters):
    """For waves.json: how hard each monster is for each tower tag, compared with the tag's other matchups (above
    1: harder than its usual). A tower's cell is first taken against the median tower's for that monster (capped
    at SCORE_CAP), then against the tower's own mean over the monsters, so a tower that's weak everywhere
    only adds where it's weakest; then averaged over the tag's solo comps at every checkpoint."""
    by_tag = {}
    for table in tables:
        median = {m: statistics.median(min(table[c][m], 1e9) for c in table) for m in monsters}
        for c, row in table.items():
            if c not in TAG_OF:
                continue  # a support mix
            ratio = {m: min(row[m] / median[m], SCORE_CAP) for m in monsters}
            mean = statistics.mean(ratio.values())
            by_tag.setdefault(TAG_OF[c], []).append({m: r / mean for m, r in ratio.items()})
    return {tag: {m: round(statistics.mean(r[m] for r in rows), 2) for m in monsters}
            for tag, rows in sorted(by_tag.items())}


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------
def gold_fmt(value):
    return "-" if math.isinf(value) else f"{value:.0f}"


def cell_fmt(result):
    value, capped = result
    return ("<" if capped else "") + gold_fmt(value)


def saved_fmt(value):
    return "x" if math.isinf(value) else percent(value)


def report(name, monsters, jobs, csv_dir=None):
    level, wave, gold, tiers = CHECKPOINTS[name]
    cells, solos, mixes = matrix(name, monsters, jobs)
    support = support_rows(cells, mixes, monsters)
    labels = [comp_label(c) for c in solos] + best_mixes(support)
    table = {c: {m: cells[c][m][0] for m in monsters} for c in labels}
    head = (f"{name}: level {level} wave {wave} (hp x{wave_hp_mult(level - 1, wave - 1):.1f}), "
            f"{gold} defender gold, tiers {', '.join(map(str, tiers))}")
    print(f"\n{'=' * len(head)}\n{head}\n{'=' * len(head)}")

    rows = [{"comp": c, **{m: cells[c][m] for m in monsters}} for c in labels]
    print_table("Tower gold to stop 100 gold of each monster (lower = counters it; '-': can't keep up "
                "at any hp; '<': capped)", rows, ["comp", *monsters], dict.fromkeys(monsters, cell_fmt))
    if support:
        print_table("Support: tower gold the slowing towers save their partner, against it alone (100%: only the "
                    "mix keeps up; x: the mix can't keep up)", support, ["comp", *monsters, "mean"],
                    {"mean": saved_fmt, **dict.fromkeys(monsters, saved_fmt)})
    gold_cols = dict.fromkeys(("best gold", "worst gold", "gold", "median"), gold_fmt)
    print_table("Counters: the comp that stops each monster for the least and the most gold", counters(table, monsters),
                ["monster", "best", "best gold", "worst", "worst gold", "spread"], gold_cols)
    print_table("Worst matchup: what the monster player drafts against each comp", worst_matchups(table, monsters),
                ["comp", "worst vs", "gold", "median", "x median"], gold_cols)
    lines = dominated(table, monsters)
    print("\nDominated\n")
    print("\n".join(f"  {line}" for line in lines) if lines else "  none")
    shown, left_out = dict(table), []
    while len(shown) > 1:  # a comp that takes most of the weight hides the rest: show the game without it too
        pt, pm, value = equilibrium(shown, monsters)
        title = f" without {', '.join(left_out)}" if left_out else ""
        print(f"\nEquilibrium{title} (value: {value:.0f} monster gold stopped per 100 tower gold; "
              "weights under 2% left out)\n")
        print("  towers:   " + ", ".join(f"{c} {w:.0%}" for c, w in sorted(pt.items(), key=lambda kv: -kv[1])
                                         if w >= 0.02))
        print("  monsters: " + ", ".join(f"{m} {w:.0%}" for m, w in sorted(pm.items(), key=lambda kv: -kv[1])
                                         if w >= 0.02))
        top = max(pt, key=pt.get)
        if pt[top] < 0.5 or len(left_out) == 2:
            break
        left_out.append(top)
        del shown[top]
    print_table("Costs: what each monster would cost to be as hard to stop per gold as the average one",
                fair_costs(table, monsters), ["monster", "cost", "stopped/100g", "fair cost"])

    if csv_dir:
        os.makedirs(csv_dir, exist_ok=True)
        path = os.path.join(csv_dir, f"matchups_{name}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["comp", *monsters])
            for c in cells:
                writer.writerow([c, *(cells[c][m][0] for m in monsters)])
        print(f"\nWrote {path}")
    return table


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--checkpoint", default=",".join(CHECKPOINTS), help=f"comma-separated: {', '.join(CHECKPOINTS)}")
    parser.add_argument("--monsters", default=",".join(MONSTERS), help="comma-separated draftable monsters")
    parser.add_argument("--jobs", type=int, default=os.cpu_count(), help="worker processes")
    parser.add_argument("--csv", help="also write each checkpoint's matrix to this directory")
    parser.add_argument("--counter-scores", action="store_true", help="print the counter scores for waves.json")
    args = parser.parse_args(argv)
    monsters = args.monsters.split(",")
    for m in monsters:
        if m not in MONSTERS:
            parser.error(f"{m} isn't a draftable monster")
    tables = []
    for name in args.checkpoint.split(","):
        if name not in CHECKPOINTS:
            parser.error(f"unknown checkpoint {name}")
        tables.append(report(name, monsters, args.jobs, args.csv))
    if args.counter_scores:
        print("\nCounter scores (waves.json counters.scores)\n")
        print(json.dumps(counter_scores(tables, monsters)))


if __name__ == "__main__":
    main()
