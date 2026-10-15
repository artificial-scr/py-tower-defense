"""Per-level balance logs.

Every level played (cleared, lost, or quit part-way) writes one JSON file:

    logs/<session>/run<NN>_[monsters_]level<NN>_<theme>_<outcome>.json

(monsters_ marks a level played on the Monsters side; its economy is the defender's, which
never changes, and the draft budget goes in each wave's gold fields.)

<session> is the launch time plus a random suffix, a new run starts each time the
game is restarted, and files are opened in exclusive-create mode, so a log is
never overwritten.

Each file has:
  level, economy, waves      what happened, wave by wave
  strongest_comp             the most valuable set of towers on the map at any point (value =
                             gold put into them), when it was reached, and what was in it
  strongest_comp_by_wave     the same for each wave: from the end of the previous wave to the
                             end of this one (the build phase plus the wave itself)
  towers_by_kind             damage, DPS, overkill, kills per tower kind (towers that
                             evolved count toward each kind for the time they spent as it)
  enemies_by_kind            spawned / killed / leaked, HP vs damage taken, time to kill
  towers, enemies            the same data per individual tower and enemy
  events                     buys, fusions, branch choices, moves, sells
  specs                      the tower and enemy stats in effect, so old logs stay readable
"""

import json
import os
import re
import secrets
from collections import defaultdict
from datetime import datetime

DAMAGE_SOURCES = ("direct", "splash", "chain", "burn")


def new_kind_stats():
    return {"wave_seconds": 0.0, "shots": 0, "hits": 0, "kills": 0, "warded": 0, "decoyed": 0, "damage": 0.0, "overkill": 0.0,
            "vs_slowed_bonus": 0.0, "by_source": defaultdict(float), "vs_enemy": defaultdict(float)}


def r(x, nd=1):
    return round(x, nd)


class LogSession:
    """One per game launch; owns the output directory and guarantees unique file names."""

    def __init__(self, root):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.dir = os.path.join(root, f"{stamp}-{secrets.token_hex(3)}")
        self.run = 0

    def write(self, name, data):
        os.makedirs(self.dir, exist_ok=True)
        base = os.path.join(self.dir, name)
        path, n = base + ".json", 1
        while True:
            try:
                with open(path, "x", encoding="utf-8") as f:
                    json.dump(data, f, indent=1)
                return path
            except FileExistsError:
                n += 1
                path = f"{base}_{n}.json"


class LevelLog:
    """Collects everything that happens during one level and writes it out at the end."""

    def __init__(self, session, level_number, theme_name, boss, path_length, lives, gold, specs, side="towers"):
        self.session = session
        self.side = side
        self.specs = specs
        self.run = session.run
        self.level_number = level_number
        self.theme_name = theme_name
        self.boss = boss
        self.path_length = path_length
        self.lives_start = lives
        self.gold_start = gold
        self.started = datetime.now()
        self.towers = []   # every tower present during the level, including sold / fused ones
        self.enemies = []  # every enemy spawned
        self.events = []
        self.waves = []
        self.earned = defaultdict(int)
        self.spent = defaultdict(int)
        self.written = None

    # ---- recording -----------------------------------------------------------
    def event(self, t, event_type, **data):
        self.events.append({"t": r(t, 2), "type": event_type, **data})

    def add_tower(self, tower):
        if tower not in self.towers:
            self.towers.append(tower)

    def start_wave(self, t, number, hp_mult, kinds, lives, gold):
        counts = defaultdict(int)
        for k in kinds:
            counts[k] += 1
        self.waves.append({"wave": number, "hp_mult": r(hp_mult, 3), "composition": dict(counts),
                           "t_start": r(t, 2), "lives_start": lives, "gold_start": gold,
                           "kills": 0, "leaks": 0, "lives_lost": 0, "kill_gold": 0, "summoned": 0,
                           "gold_stolen": 0})

    def current_wave(self):
        return self.waves[-1] if self.waves else None

    def end_wave(self, t, lives, gold, bonus):
        w = self.current_wave()
        w.update(t_end=r(t, 2), duration=r(t - w["t_start"], 2), lives_end=lives, gold_end=gold, bonus=bonus)

    # ---- output --------------------------------------------------------------
    def finish(self, outcome, t, lives, gold, strongest_comp=None, comps_by_wave=None):
        """Write the log. The comps are tracked by the game (see progress.comp_snapshot)."""
        if self.written:
            return self.written
        if self.waves and "t_end" not in self.waves[-1]:
            w = self.waves[-1]
            w.update(t_end=r(t, 2), duration=r(t - w["t_start"], 2), lives_end=lives, gold_end=gold,
                     unfinished=True)
        data = {
            "level": {"number": self.level_number, "theme": self.theme_name, "boss_level": self.boss, "side": self.side,
                      "run": self.run, "outcome": outcome, "game_seconds": r(t, 2),
                      "real_seconds": r((datetime.now() - self.started).total_seconds(), 1),
                      "started_at": self.started.isoformat(timespec="seconds"),
                      "waves_started": len(self.waves), "lives_start": self.lives_start, "lives_end": lives,
                      "path_length_px": r(self.path_length)},
            "economy": {"gold_start": self.gold_start, "gold_end": gold,
                        "earned": dict(self.earned), "spent": dict(self.spent)},
            "strongest_comp": strongest_comp,
            "strongest_comp_by_wave": {str(w): c for w, c in sorted((comps_by_wave or {}).items())},
            "waves": self.waves,
            "towers_by_kind": self.towers_by_kind(),
            "enemies_by_kind": self.enemies_by_kind(t),
            "towers": [self.tower_record(tw) for tw in self.towers],
            "enemies": [self.enemy_record(e, t) for e in self.enemies],
            "events": self.events,
            "specs": self.specs,
        }
        slug = re.sub(r"[^a-z0-9]+", "-", self.theme_name.lower()).strip("-")
        side = "monsters_" if self.side == "monsters" else ""
        name = f"run{self.run:02d}_{side}level{self.level_number:02d}_{slug}_{outcome}"
        self.written = self.session.write(name, data)
        return self.written

    def towers_by_kind(self):
        total = sum(s["damage"] for tw in self.towers for s in tw.stats.values()) or 1
        agg = {}
        for tw in self.towers:
            for kind, s in tw.stats.items():
                a = agg.setdefault(kind, {"instances": 0, **new_kind_stats()})
                a["instances"] += 1
                for f in ("wave_seconds", "shots", "hits", "kills", "warded", "decoyed", "damage", "overkill", "vs_slowed_bonus"):
                    a[f] += s[f]
                for src, v in s["by_source"].items():
                    a["by_source"][src] += v
                for ek, v in s["vs_enemy"].items():
                    a["vs_enemy"][ek] += v
        out = {}
        for kind, a in sorted(agg.items(), key=lambda kv: -kv[1]["damage"]):
            dealt = a["damage"] + a["overkill"]
            out[kind] = {
                "instances": a["instances"],
                "damage": r(a["damage"]),
                "damage_share_pct": r(100 * a["damage"] / total),
                "wave_seconds": r(a["wave_seconds"]),
                "dps_per_tower": r(a["damage"] / a["wave_seconds"]) if a["wave_seconds"] else None,
                "shots": a["shots"], "hits": a["hits"], "kills": a["kills"], "warded": a["warded"],
                "decoyed": a["decoyed"],
                "overkill": r(a["overkill"]),
                "overkill_pct": r(100 * a["overkill"] / dealt) if dealt else 0.0,
                "vs_slowed_bonus": r(a["vs_slowed_bonus"]),
                "by_source": {k: r(v) for k, v in a["by_source"].items()},
                "vs_enemy": {k: r(v) for k, v in a["vs_enemy"].items()},
            }
        return out

    def enemies_by_kind(self, t):
        agg = {}
        for e in self.enemies:
            a = agg.setdefault(e.kind, {"spawned": 0, "summoned": 0, "killed": 0, "leaked": 0, "alive_at_end": 0,
                                        "lives_taken": 0, "hp_total": 0.0, "damage_taken": 0.0,
                                        "kill_times": [], "death_progress": [], "slowed_seconds": 0.0,
                                        "burning_seconds": 0.0, "damage_from": defaultdict(float)})
            a["spawned"] += 1
            a["summoned"] += e.origin != "wave"
            a["hp_total"] += e.max_hp
            a["damage_taken"] += e.max_hp - max(e.hp, 0)
            a["slowed_seconds"] += e.slowed_seconds
            a["burning_seconds"] += e.burning_seconds
            for tk, v in e.damage_from.items():
                a["damage_from"][tk] += v
            if e.escaped:
                a["leaked"] += 1
                a["lives_taken"] += e.spec["damage"]
            elif not e.alive:
                a["killed"] += 1
                a["kill_times"].append(e.end_t - e.spawn_t)
                a["death_progress"].append(e.travelled / self.path_length)
            else:
                a["alive_at_end"] += 1
        out = {}
        for kind, a in agg.items():
            kt, dp = a.pop("kill_times"), a.pop("death_progress")
            a["avg_seconds_to_kill"] = r(sum(kt) / len(kt), 2) if kt else None
            a["avg_path_progress_at_death"] = r(sum(dp) / len(dp), 3) if dp else None
            a["leak_rate_pct"] = r(100 * a["leaked"] / a["spawned"])
            a["hp_total"] = r(a["hp_total"])
            a["damage_taken"] = r(a["damage_taken"])
            a["slowed_seconds"] = r(a["slowed_seconds"])
            a["burning_seconds"] = r(a["burning_seconds"])
            a["damage_from"] = {k: r(v) for k, v in sorted(a["damage_from"].items(), key=lambda kv: -kv[1])}
            out[kind] = a
        return out

    @staticmethod
    def tower_record(tw):
        return {"id": tw.uid, "kind": tw.kind, "tier": tw.tier, "tile": list(tw.tile), "status": tw.status,
                "gold_spent": tw.spent, "history": tw.history,
                "stats_by_kind": {k: {**{f: (r(v) if isinstance(v, float) else v) for f, v in s.items()
                                         if f not in ("by_source", "vs_enemy")},
                                      "by_source": {src: r(v) for src, v in s["by_source"].items()},
                                      "vs_enemy": {ek: r(v) for ek, v in s["vs_enemy"].items()}}
                                  for k, s in tw.stats.items()}}

    def enemy_record(self, e, t):
        outcome = "leaked" if e.escaped else "killed" if not e.alive else "alive"
        end = e.end_t if e.end_t is not None else t
        return {"id": e.uid, "kind": e.kind, "origin": e.origin, "wave": e.wave, "outcome": outcome,
                "max_hp": r(e.max_hp), "damage_taken": r(e.max_hp - max(e.hp, 0)),
                "overkill_received": r(e.overkill), "seconds_alive": r(end - e.spawn_t, 2),
                "path_progress": r(e.travelled / self.path_length, 3),
                "slowed_seconds": r(e.slowed_seconds, 2), "burning_seconds": r(e.burning_seconds, 2),
                "killed_by": e.killed_by, "damage_from": {k: r(v) for k, v in e.damage_from.items()}}
