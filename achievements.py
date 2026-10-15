"""Tower unlocks: the achievements in achievements.json, and the tracker that counts them.

A new profile owns only the start towers (the Gun). Every other tower is unlocked for good by its
achievement, or, for the first few tier 4 towers ever fused, by the fusion itself (a discovery). Only
the Towers side counts toward achievements. See DESIGN.md section 11.

The file is read and checked once, at import, like towers.json: a mistake stops the game with a
message naming the achievement and the problem.
"""

import os
from collections import defaultdict, deque

from balance_log import DAMAGE_SOURCES
from monsters import ENEMY_TYPES
from towers import CROSS, EVOLVE, LINES, TOWER_LINES, TOWERS, read_json

ACHIEVEMENTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "achievements.json")

# condition -> (fields it needs, fields it may have); see the comment at the top of achievements.json
CONDITIONS = {
    "towers_on_map": (("kind",), ()),
    "in_range": ((), ()),
    "slowed_at_once": ((), ()),
    "multi_kill": (("by",), ()),
    "burst": (("seconds",), ()),
    "kills": ((), ("by", "enemy", "how", "slowed", "scope")),
    "leaks": ((), ("enemy", "scope")),
    "boss_kill": (("boss", "seconds"), ()),
    "wave_cleared": (("min_monsters",), ()),
    "level_cleared": ((), ("min_level", "no_leaks", "only_line")),
    "pass_won": ((), ("finale", "min_gold")),
}
# Conditions measured as a peak (the best seen counts) rather than added up over time.
PEAKS = ("towers_on_map", "in_range", "slowed_at_once", "multi_kill", "burst")
GOAL_FIELDS = ("desc", "condition", "target")
SCOPES = ("level", "ever")
SAMPLE_EVERY = 6  # updates between checks of in_range and slowed_at_once (they look at every tower / enemy)
BURST_MEMORY = 10.0  # seconds of kill times kept for burst goals


def load_achievements(path):
    """Return (start towers, discoveries, {achievement id: achievement}) from achievements.json."""
    data = read_json(path)
    name = os.path.basename(path)

    def fail(message):
        raise ValueError(f"{name}: {message}")

    start = list(data["start"])
    for kind in start:
        if kind not in TOWERS or TOWERS[kind]["tier"] != 1:
            fail(f"start: {kind!r} isn't a tier 1 tower")
    achievements, unlocked_by = {}, {}
    for key, raw in data["achievements"].items():
        def bad(message):
            fail(f"achievement {key!r}: {message}")
        tower = raw.get("unlocks")
        if tower not in TOWERS:
            bad(f"unlocks {tower!r}, which isn't in towers.json")
        if tower in start:
            bad(f"unlocks {tower!r}, which every profile starts with")
        if tower in unlocked_by:
            bad(f"{tower!r} is already unlocked by {unlocked_by[tower]!r}")
        unlocked_by[tower] = key
        goals = raw.get("goals") or bad("needs at least one goal")
        for i, goal in enumerate(goals):
            missing = [f for f in GOAL_FIELDS if f not in goal]
            if missing:
                bad(f"goal {i + 1}: missing fields {missing}")
            if goal["condition"] not in CONDITIONS:
                bad(f"goal {i + 1}: condition must be one of {tuple(CONDITIONS)}")
            needs, may = CONDITIONS[goal["condition"]]
            unknown = [f for f in goal if f not in GOAL_FIELDS + needs + may]
            missing = [f for f in needs if f not in goal]
            if unknown or missing:
                bad(f"goal {i + 1}: " + (f"unknown fields {unknown}" if unknown else f"missing fields {missing}"))
            for field in ("kind", "by"):
                for k in [goal[field]] if isinstance(goal.get(field), str) else goal.get(field, []):
                    if k not in TOWERS:
                        bad(f"goal {i + 1}: {k!r} isn't a tower")
            for k in goal.get("enemy", []) + ([goal["boss"]] if "boss" in goal else []):
                if k not in ENEMY_TYPES:
                    bad(f"goal {i + 1}: {k!r} isn't a monster")
            if goal.get("how", "direct") not in DAMAGE_SOURCES:
                bad(f"goal {i + 1}: how must be one of {DAMAGE_SOURCES}")
            if goal.get("scope", "ever") not in SCOPES:
                bad(f"goal {i + 1}: scope must be one of {SCOPES}")
            if goal.get("only_line", next(iter(LINES))) not in LINES:
                bad(f"goal {i + 1}: {goal['only_line']!r} isn't a tower line")
        achievements[key] = {"name": raw["name"], "unlocks": tower,
                             "goals": [{"scope": "ever", **g} for g in goals]}
    never = [k for k in TOWERS if k not in start and k not in unlocked_by]
    if never:
        fail(f"towers no achievement unlocks: {never}")
    return start, int(data["discoveries"]), achievements


START_TOWERS, DISCOVERIES, ACHIEVEMENTS = load_achievements(ACHIEVEMENTS_FILE)
UNLOCKED_BY = {a["unlocks"]: key for key, a in ACHIEVEMENTS.items()}  # tower -> achievement id
# tower -> the towers fused to make it: the one before it in its line, or a final's two tier 3 parents.
# A tower's achievement is hidden, and counts nothing, until the player owns all of them.
PREREQUISITES = {k: () for k in TOWERS}
for _parent, _options in EVOLVE.items():
    for _kind in _options:
        PREREQUISITES[_kind] = (_parent,)
for _parents, _final in CROSS.items():
    PREREQUISITES[_final] = tuple(sorted(_parents, key=list(TOWERS).index))


def goal_key(achievement, index):
    """The key a goal's progress is stored under in the profile."""
    return f"{achievement}/{index}"


class AchievementTracker:
    """Counts the Towers side's achievements and unlocks towers in the profile as goals are met.

    main.Game calls the on_* hooks and tick(); `on_unlock(kind)` is called once per tower unlocked.
    Progress that lasts (scope ever, and the best peaks) lives in profile.achievements and is written
    to disk by flush(); counts for one level live here and restart with start_level()."""

    def __init__(self, profile, on_unlock):
        self.profile = profile
        self.on_unlock = on_unlock
        self.dirty = False
        self.start_level()

    def start_level(self):
        self.level_counts = defaultdict(int)  # goal key -> count this level (scope level)
        self.kill_times = deque()
        self.frame_kills = defaultdict(int)  # (tower uid, tower kind) -> kills this update, burns left out
        self.lines_used = set()  # tower lines on the map at some point this level
        self.leaked = False
        self.updates = 0

    # ---- progress ---------------------------------------------------------------
    def available(self, kind):
        """Whether a locked tower's achievement is shown and counted: the player owns every tower it's fused from."""
        return not self.profile.has_tower(kind) and all(self.profile.has_tower(p) for p in PREREQUISITES[kind])

    def missing_prerequisites(self, kind):
        """The towers `kind` is fused from that the player doesn't own yet."""
        return [p for p in PREREQUISITES[kind] if not self.profile.has_tower(p)]

    def open_goals(self, condition):
        """(key, goal) for every goal of `condition` whose tower is locked but available. A list, made before
        any of them count, so a tower unlocked by this event doesn't let its children count the same event."""
        return [(goal_key(aid, i), goal) for aid, ach in ACHIEVEMENTS.items() if self.available(ach["unlocks"])
                for i, goal in enumerate(ach["goals"]) if goal["condition"] == condition]

    def reach(self, key, goal, value):
        """`value` is the goal's progress now: keep the best, and unlock the tower once it's met."""
        best = self.profile.achievements.get(key, 0)
        if value > best:
            self.profile.achievements[key] = value
            self.dirty = True
        if value >= goal["target"]:
            kind = ACHIEVEMENTS[key.split("/")[0]]["unlocks"]
            if self.profile.unlock_tower(kind):
                self.on_unlock(kind)

    def add(self, key, goal, amount=1):
        """Count toward an added-up goal, in this level or over all time (its scope)."""
        if goal["scope"] == "level":
            self.level_counts[key] += amount
            value = self.level_counts[key]
        else:
            value = self.profile.achievements.get(key, 0) + amount
        self.reach(key, goal, value)

    def progress(self, key, goal):
        """What to show for a goal: this level's count for level goals, else the best or total so far."""
        if goal["scope"] == "level" and goal["condition"] not in PEAKS:
            return self.level_counts.get(key, 0)
        return self.profile.achievements.get(key, 0)

    def closest(self):
        """(tower, goal, progress) for the available tower nearest to unlocking, or None."""
        best = None
        for aid, ach in ACHIEVEMENTS.items():
            if not self.available(ach["unlocks"]):
                continue
            for i, goal in enumerate(ach["goals"]):
                value = self.progress(goal_key(aid, i), goal)
                share = min(value / goal["target"], 1)
                if best is None or share > best[0]:
                    best = (share, ach["unlocks"], goal, value)
        return best and best[1:]

    def flush(self):
        """Write the progress that lasts to disk (unlocks are written as they happen)."""
        if self.dirty:
            self.dirty = False
            self.profile.save()

    # ---- hooks --------------------------------------------------------------------
    def on_death(self, enemy, clock):
        """A monster left the map: killed, or through to the end of the path."""
        if enemy.escaped:
            self.leaked = True
            for key, goal in self.open_goals("leaks"):
                if enemy.kind in goal.get("enemy", [enemy.kind]):
                    self.add(key, goal)
            return
        by = enemy.killed_by or {}
        for key, goal in self.open_goals("kills"):
            if (by.get("kind") in goal.get("by", [by.get("kind")]) and enemy.kind in goal.get("enemy", [enemy.kind])
                    and by.get("how") == goal.get("how", by.get("how"))
                    and enemy.slowed == goal.get("slowed", enemy.slowed)):
                self.add(key, goal)
        for key, goal in self.open_goals("boss_kill"):
            if enemy.kind == goal["boss"] and clock - enemy.spawn_t <= goal["seconds"]:
                self.reach(key, goal, 1)
        if by and by["how"] != "burn":
            self.frame_kills[(by["tower"], by["kind"])] += 1
        self.kill_times.append(clock)
        while self.kill_times[0] < clock - BURST_MEMORY:
            self.kill_times.popleft()
        for key, goal in self.open_goals("burst"):
            self.reach(key, goal, sum(1 for t in self.kill_times if t >= clock - goal["seconds"]))

    def tick(self, towers, enemies, in_wave):
        """After every update: the peaks that depend on what's on the map."""
        counts = defaultdict(int)
        for t in towers:
            counts[t.kind] += 1
            self.lines_used.update(TOWER_LINES[t.kind])
        for key, goal in self.open_goals("towers_on_map"):
            self.reach(key, goal, counts[goal["kind"]])
        # the kills one tower made in a single update (burns left out) all came from one shot
        for key, goal in self.open_goals("multi_kill"):
            self.reach(key, goal, max((n for (_, kind), n in self.frame_kills.items() if kind == goal["by"]),
                                      default=0))
        self.frame_kills.clear()
        self.updates += 1
        if not in_wave or self.updates % SAMPLE_EVERY:
            return
        alive = [e for e in enemies if e.alive]
        for key, goal in self.open_goals("in_range"):
            self.reach(key, goal, max((sum(1 for e in alive if e.pos.distance_to(t.pos) <= t.range) for t in towers),
                                      default=0))
        for key, goal in self.open_goals("slowed_at_once"):
            self.reach(key, goal, sum(1 for e in alive if e.slowed))

    def on_wave_cleared(self, monsters):
        """A wave ended with the level still going; `monsters` spawned in it (splits and summons included)."""
        for key, goal in self.open_goals("wave_cleared"):
            if monsters >= goal["min_monsters"]:
                self.add(key, goal)
        self.flush()

    def on_level_cleared(self, level):
        """Level `level` (1-based) was cleared on the Towers side."""
        for key, goal in self.open_goals("level_cleared"):
            only = goal.get("only_line")
            if (level >= goal.get("min_level", 1) and not (goal.get("no_leaks") and self.leaked)
                    and (not only or self.lines_used == {only})):
                self.add(key, goal)
        self.flush()

    def on_pass_won(self, finale, gold):
        """A Towers pass was won; `finale` if it ended early on a finale wave."""
        for key, goal in self.open_goals("pass_won"):
            if (finale or not goal.get("finale")) and gold >= goal.get("min_gold", 0):
                self.add(key, goal)
        self.flush()
