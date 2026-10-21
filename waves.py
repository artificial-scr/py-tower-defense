"""Generated Towers-side waves, from waves.json (DESIGN.md section 12): the monsters each level brings in,
the packs its waves are made of, and the counters the scouts send against the towers on the map.

Read and checked once, at import. A mistake stops the game with a message naming the problem.
"""

import math
import os
import random
from collections import Counter
from dataclasses import dataclass, field

from levels import BOSS_LEVELS, WAVES_PER_LEVEL, generated_hp_mult
from monsters import ENEMY_TYPES
from towers import TOWERS, read_json

WAVES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "waves.json")

SLOTS = ("new", "pattern", "stream")
FIELDS = ("threat", "budget", "pack_pause", "start", "levels", "roles", "patterns", "counters")
BUDGET_FIELDS = ("base", "per_wave", "challenge")
COUNTER_FIELDS = ("share", "role_weight", "main_tag_from", "escalation", "escalation_max", "tags", "scores",
                  "min_score", "options", "cluster", "hoard")
PATTERN_REACH = 1.25  # a pattern fits a slot when its threat is at most this many times the slot's


def load_waves(path):
    """Return the wave rules from waves.json, checked (see the comment at the top of the file)."""
    data = read_json(path)
    name = os.path.basename(path)

    def fail(what, message):
        raise ValueError(f"{name}: {what}: {message}")

    def check_fields(what, raw, required):
        missing = [f for f in required if f not in raw]
        unknown = [f for f in raw if f not in required + ("_comment",)]
        if missing or unknown:
            fail(what, f"missing fields {missing}" if missing else f"unknown fields {unknown}")

    def check_groups(what, groups):
        if not (isinstance(groups, list) and groups):
            fail(what, "must be a list of [kind, count]")
        for g in groups:
            if not (isinstance(g, list) and len(g) == 2 and isinstance(g[1], int) and g[1] >= 1):
                fail(what, f"{g!r} must be [kind, count], count 1 or more")
            check_kind(what, g[0])

    check_fields("file", data, FIELDS)
    threat = data["threat"]
    for kind, t in threat.items():
        if kind not in ENEMY_TYPES or ENEMY_TYPES[kind]["draft"] == "boss":
            fail("threat", f"{kind!r} isn't a monster (bosses come on their own)")
        if not (isinstance(t, (int, float)) and t > 0):
            fail("threat", f"{kind!r} must be positive")

    def check_kind(what, kind):
        if kind not in threat:
            fail(what, f"{kind!r} has no threat")

    check_fields("budget", data["budget"], BUDGET_FIELDS)
    if not all(isinstance(data["budget"][f], (int, float)) and data["budget"][f] > 0 for f in BUDGET_FIELDS):
        fail("budget", f"{', '.join(BUDGET_FIELDS)} must be positive")
    if not (isinstance(data["pack_pause"], (int, float)) and data["pack_pause"] >= 0):
        fail("pack_pause", "must be 0 or more seconds")

    for kind in data["start"]:
        check_kind("start", kind)
    on_roster = set(data["start"])
    if not data["levels"]:
        fail("levels", "needs at least one level")
    for i, level in enumerate(data["levels"]):
        what = f"level {i + 1}"
        check_fields(what, level, ("new",) + tuple(f for f in ("waves", "elite") if f in level))
        if "elite" in level and not ENEMY_TYPES.get(level["elite"], {}).get("elite"):
            fail(what, f"elite {level['elite']!r} isn't an elite (monsters.json)")
        for kind in level["new"]:
            check_kind(what, kind)
            if kind in on_roster:
                fail(what, f"{kind!r} is already on the roster")
        on_roster |= set(level["new"])
        if "waves" in level:
            if len(level["waves"]) != WAVES_PER_LEVEL:
                fail(what, f"scripts {WAVES_PER_LEVEL} waves or none")
            for w, wave in enumerate(level["waves"]):
                if not (isinstance(wave, list) and wave):
                    fail(f"{what} wave {w + 1}", "must be a list of packs")
                for pack in wave:
                    check_groups(f"{what} wave {w + 1}", pack)
                    off = [k for k, _ in pack if k not in on_roster]
                    if off:
                        fail(f"{what} wave {w + 1}", f"{off} aren't on the roster yet")

    roles = data["roles"]
    if len(roles) != WAVES_PER_LEVEL:
        fail("roles", f"needs one per wave ({WAVES_PER_LEVEL})")
    for role in roles:
        check_fields("role", role, ("name", "slots"))
        what = f"role {role['name']!r}"
        if not role["slots"] or any(s not in SLOTS or not share > 0 for s, share in role["slots"]):
            fail(what, f"slots must be [{' | '.join(SLOTS)}, share], shares positive")
        if abs(sum(share for _, share in role["slots"]) - 1) > 1e-6:
            fail(what, "slot shares must add up to 1")

    if "stream" not in data["patterns"]:
        fail("patterns", "needs a 'stream' pattern")
    for key, groups in data["patterns"].items():
        check_groups(f"pattern {key!r}", groups)

    counters = data["counters"]
    check_fields("counters", counters, COUNTER_FIELDS)
    if not (counters["share"] and all(0 <= s <= 1 for s in counters["share"])):
        fail("counters", "share must be a list of shares, 0 to 1")
    if sorted(counters["role_weight"]) != sorted(r["name"] for r in roles):
        fail("counters", "role_weight needs one weight for each role")
    if not 0 < counters["main_tag_from"] <= 1:
        fail("counters", "main_tag_from must be a share above 0, up to 1")
    if not (counters["escalation"] >= 0 and counters["escalation_max"] >= 0):
        fail("counters", "escalation and escalation_max must be 0 or more")
    if not (counters["min_score"] > 0 and isinstance(counters["options"], int) and counters["options"] >= 1):
        fail("counters", "min_score must be positive and options a whole number, 1 or more")
    if sorted(counters["scores"]) != sorted(counters["tags"]):
        fail("counters", "scores needs one table for each tag")
    for tag, scores in counters["scores"].items():
        for kind, score in scores.items():
            check_kind(f"counters scores {tag!r}", kind)
            if not score > 0:
                fail(f"counters scores {tag!r}", f"{kind!r} must be positive")
    tagged = Counter()
    for tag, raw in counters["tags"].items():
        what = f"counters tag {tag!r}"
        check_fields(what, raw, ("label", "towers"))
        unknown = [k for k in raw["towers"] if k not in TOWERS]
        if unknown:
            fail(what, f"{unknown} aren't towers")
        tagged.update(raw["towers"])
    if set(tagged) != set(TOWERS) or max(tagged.values()) > 1:
        fail("counters tags", "every tower needs exactly one tag")
    check_fields("counters cluster", counters["cluster"], ("label", "kind", "radius", "towers", "count"))
    check_kind("counters cluster", counters["cluster"]["kind"])
    check_fields("counters hoard", counters["hoard"], ("label", "kind", "ratio", "max"))
    check_kind("counters hoard", counters["hoard"]["kind"])
    return data


RULES = load_waves(WAVES_FILE)
THREAT = RULES["threat"]
COUNTERS = RULES["counters"]
TAG_OF = {tower: tag for tag, raw in COUNTERS["tags"].items() for tower in raw["towers"]}


@dataclass
class Wave:
    kinds: list  # the spawn queue
    hp_mult: float
    pauses: dict = field(default_factory=dict)  # monsters spawned so far -> seconds to wait before the next
    counter: dict | None = None  # what the scouts countered and with what (see add_counters)


def plan(level_idx):
    """The level's entry in waves.json; levels past the list get the last one, with nothing new or scripted."""
    levels = RULES["levels"]
    return levels[level_idx] if level_idx < len(levels) else {"new": []}


def level_elite(level_idx):
    """The elite that ends a level's last wave when no boss does (levels past the list keep the last one's)."""
    levels = RULES["levels"]
    return levels[min(level_idx, len(levels) - 1)].get("elite", "champion")


def roster(level_idx):
    """The monsters generated waves can use on a level: the start, and everything brought in up to it."""
    kinds = list(RULES["start"])
    for level in RULES["levels"][:level_idx + 1]:
        kinds += level["new"]
    return kinds


def threat(kinds):
    return sum(THREAT.get(k, 0) for k in kinds)


def wave_budget(level_idx, wave_idx):
    """How much threat a generated wave has, before the last wave's elite or boss."""
    b = RULES["budget"]
    return b["challenge"] * (b["base"] + b["per_wave"] * (level_idx * WAVES_PER_LEVEL + wave_idx))


@dataclass
class Pack:
    kinds: list
    block: int | None = 0  # what counters may take out: monsters one by one (0: streams and scripted packs), whole
    # repeats of a pattern this long, or nothing (None: the level's newcomers)


def pattern_pack(key, budget, on_roster, rng):
    """A pattern repeated to fill about `budget` threat (the stream keeps only kinds on the roster, shuffled)."""
    groups = [(k, n) for k, n in RULES["patterns"][key] if k in on_roster]
    block = [k for k, n in groups for _ in range(n)]
    kinds = block * max(1, round(budget / threat(block)))
    if key == "stream":
        rng.shuffle(kinds)
        return Pack(kinds)
    return Pack(kinds, len(block))


def newcomer_pack(new, budget):
    """The level's newcomers sharing `budget`, at least one of each."""
    return Pack([k for k in new for _ in range(max(1, round(budget / len(new) / THREAT[k])))], None)


def base_packs(level_idx, wave_idx, rng):
    """The wave before counters, as Packs."""
    level = plan(level_idx)
    if "waves" in level:
        return [Pack([k for k, n in pack for _ in range(n)]) for pack in level["waves"][wave_idx]]
    on_roster = set(roster(level_idx))
    budget = wave_budget(level_idx, wave_idx)
    packs, planned, spent = [], 0, 0
    for slot, share in RULES["roles"][wave_idx]["slots"]:
        planned += budget * share
        b = planned - spent  # a slot that overshot takes from the next ones
        if slot == "new" and level["new"]:
            packs.append(newcomer_pack(level["new"], b))
        elif b > 0:
            fits = [key for key, groups in RULES["patterns"].items()
                    if key != "stream" and all(k in on_roster for k, _ in groups)
                    and threat(k for k, n in groups for _ in range(n)) <= PATTERN_REACH * b]
            packs.append(pattern_pack(rng.choice(fits) if slot != "stream" and fits else "stream", b, on_roster, rng))
        else:
            continue
        spent += threat(packs[-1].kinds)
    return packs


def counter_share(level_idx, wave_idx, report):
    """The share of the wave the scouts' counters may take: the level's, weighted by the wave's role, plus
    escalation while the same tag stays on top."""
    shares = COUNTERS["share"]
    share = shares[min(level_idx, len(shares) - 1)] * COUNTERS["role_weight"][RULES["roles"][wave_idx]["name"]]
    if share > 0 and report["main"]:
        share += min(COUNTERS["escalation_max"], COUNTERS["escalation"] * (report["streak"] - 1))
    return share


def pick(options, budget):
    """Counters taken in turn from `options` while they fit in `budget` threat."""
    picked = []
    while fit := [k for k in options if THREAT[k] <= budget]:
        for k in fit:
            if THREAT[k] <= budget:
                picked.append(k)
                budget -= THREAT[k]
    return picked


def counter_options(report, on_roster):
    """What the scouts send against the tag on top: the roster monsters its towers find hardest (counters.scores),
    hardest first, at least min_score, `options` at most (the hoard and cluster counters come on their own)."""
    if not report["main"]:
        return []
    scores = COUNTERS["scores"][report["main"]]
    special = {COUNTERS["hoard"]["kind"], COUNTERS["cluster"]["kind"]}
    ranked = sorted((k for k in on_roster if k in scores and k not in special), key=lambda k: -scores[k])
    return [k for k in ranked if scores[k] >= COUNTERS["min_score"]][:COUNTERS["options"]]


def take_out(packs, amount, keep):
    """Take at least `amount` threat out of the packs, from the back of the wave: single monsters from streams
    and scripted packs first, then a pattern's whole repeats. Never a monster in `keep` (they counter the towers
    already) or a newcomer. Returns the threat taken out."""
    taken = 0
    for p in reversed(packs):
        for i in range(len(p.kinds) - 1, -1, -1):
            if p.block == 0 and taken < amount and p.kinds[i] not in keep:
                taken += THREAT[p.kinds.pop(i)]
    for p in reversed(packs):
        while p.block and p.kinds and taken < amount and not keep & set(p.kinds[-p.block:]):
            taken += threat(p.kinds[-p.block:])
            del p.kinds[-p.block:]
    return taken


def add_counters(packs, level_idx, wave_idx, report):
    """Swap part of the wave for monsters that counter what the scouts saw (counter_options). Returns (packs, what
    was done, or None): looters hide in the middle of the heaviest pack, the rest come as a pack of their own
    before the last one. What they take out of the wave is worth as much as they are. The reasons go main tag
    first."""
    share = counter_share(level_idx, wave_idx, report)
    if share <= 0:
        return packs, None
    on_roster = set(roster(level_idx))
    hidden, extra = [], []
    hoard, cluster = COUNTERS["hoard"], COUNTERS["cluster"]
    if hoard["kind"] in on_roster and report["value"] > 0:
        hidden = [hoard["kind"]] * min(hoard["max"], int(report["gold"] // (hoard["ratio"] * report["value"])))
    if cluster["kind"] in on_roster and report["cluster"] >= cluster["towers"]:
        extra = [cluster["kind"]] * cluster["count"][report["cluster"] > cluster["towers"]]
    tag = report["main"]
    options = counter_options(report, on_roster)
    want = share * threat(k for p in packs for k in p.kinds)
    answer = pick(options, want - threat(hidden + extra))
    if not (hidden or extra or answer):
        return packs, None

    packs = [Pack(list(p.kinds), p.block) for p in packs]
    taken = take_out(packs, threat(hidden + extra + answer), set(options))
    answer += pick(options, taken - threat(hidden + extra + answer))  # a whole pattern taken out leaves room
    answer.sort(key=options.index)  # each kind together: a swarm comes as one burst
    reasons = [label for label, added in ((tag and COUNTERS["tags"][tag]["label"], answer),
                                          (cluster["label"], extra), (hoard["label"], hidden)) if added]
    packs = [p for p in packs if p.kinds]
    if extra or answer:
        packs.insert(max(0, len(packs) - 1), Pack(extra + answer, None))
    if hidden:
        heaviest = max(packs, key=lambda p: threat(p.kinds)).kinds
        n = len(heaviest)
        for j, k in enumerate(hidden):
            heaviest.insert(round(n * (j + 1) / (len(hidden) + 1)) + j, k)
    return packs, {"share": round(share, 3), "tag": tag, "reasons": reasons,
                   "added": dict(Counter(hidden + extra + answer))}


def make_wave(level_idx, wave_idx, report=None):
    """The generated wave for a level's wave, with counters to what the scouts reported (see scout). The
    same level and wave always give the same wave before counters."""
    rng = random.Random(level_idx * WAVES_PER_LEVEL + wave_idx)
    packs = base_packs(level_idx, wave_idx, rng)
    counter = None
    if report:
        packs, counter = add_counters(packs, level_idx, wave_idx, report)
    kinds, pauses = [], {}
    for pack in packs:
        if kinds:
            pauses[len(kinds)] = RULES["pack_pause"]
        kinds += pack.kinds
    if wave_idx == WAVES_PER_LEVEL - 1:
        kinds.append(BOSS_LEVELS.get(level_idx + 1) or level_elite(level_idx))
    return Wave(kinds, generated_hp_mult(level_idx, wave_idx), pauses, counter)


def wave_value(level_idx, wave_idx):
    """The monster player's budget for a wave before bonuses: what the generated wave without counters is
    worth (the sum of its monsters' costs)."""
    return sum(ENEMY_TYPES[k]["cost"] for k in make_wave(level_idx, wave_idx).kinds)


def scout(towers, gold, path_points, previous=None):
    """What the scouts report after a wave: towers is (kind, gold spent, centre, damage dealt in the wave)
    for each tower on the map, path_points the points along the path a saboteur could stand on, previous
    the last report this level. The tags' shares are of the damage dealt (what actually holds the line: one
    Absolute Zero can outdo three Mortars that cost more), or of the gold when nothing dealt any.
    The report is plain data (it goes into the balance log)."""
    value = sum(spent for _, spent, _, _ in towers)
    by = "damage" if sum(damage for *_, damage in towers) > 0 else "gold"
    weight_by_tag = Counter()
    for kind, spent, _, damage in towers:
        weight_by_tag[TAG_OF[kind]] += damage if by == "damage" else spent
    total = sum(weight_by_tag.values())
    shares = {tag: w / total for tag, w in weight_by_tag.items()} if total else {}
    top = max(shares, key=shares.get, default=None)
    main = top if top and shares[top] >= COUNTERS["main_tag_from"] else None
    streak = previous["streak"] + 1 if main and previous and previous["main"] == main else int(bool(main))
    radius = COUNTERS["cluster"]["radius"]
    cluster = max((sum(1 for _, _, c, _ in towers if math.dist(c, p) <= radius) for p in path_points),
                  default=0)
    return {"tags": {t: round(s, 3) for t, s in shares.items()}, "by": by, "main": main, "streak": streak,
            "cluster": cluster, "value": value, "gold": gold}
