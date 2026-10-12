"""A roguelike tower defense game built with pygame-ce (the full design is in DESIGN.md).

Towers are never upgraded directly: they evolve by fusing.

  Tier 1  Gun, Cannon, Frost (bought from the panel)
  Tier 2  two identical tier 1 towers fuse into Rifle / Mortar / Chiller
  Tier 3  two identical tier 2 towers fuse, and you pick one of two branches
  Tier 4  two tier 3 towers from *different* lines fuse into one of 12 final,
          cross-type towers (press T in game to see the whole tree)

There are 10 levels, each with its own color theme and path (levels.py keeps 10
more as a backup, switched off by LEVEL_COUNT). Level 10 is a boss level: its
last wave ends with a boss that summons minions, resists slows, and takes every
life if it gets through.

A run is a series of passes of the 10 levels, switching sides after level 10:
Towers (build and defend) then Monsters (attack.py: draft waves against your own
tower records) then Towers again (against your own monster records), and so on.
Losing a level ends the run. On the Monsters side the defender's lives last the
whole pass: each level has to take at least one, and the pass is won (early, if
need be) when the last one goes. Records, unlock cards and milestones are permanent
(progress.Profile, in profile.json); the run in progress is saved to
savegame.json at the start of every level.

Controls (Towers side; the Monsters side's are in attack.py)
--------
1 / 2 / 3      pick a tower to build (Gun, Cannon, Frost)
Left click     place the picked tower / select an existing tower
Drag a tower   move it to any free tile, at any time; drop it on a tower it can
               fuse with to evolve it (dropping a bought tower works too)
Right click    cancel placement / deselect (Esc also works)
Esc            cancel / close; with nothing to cancel it asks to quit (Esc again quits)
S              sell the selected tower
B              rebuild the previous level's towers (see below)
C              continue the saved run (on the start screen)
T              show the evolution tree
Space          start the next wave, continue to the next level, or switch sides after level 10
F              cycle game speed: 1x, 2x, 4x, 10x (Shift+F goes back)
P              pause
O              settings (display scale, ambient effects); also shown at launch
R              a new run, once the run is over

Moving to the next level refunds every tower; Rebuild then buys them back as they were
(same kinds, same price), strongest first, each on the free tile covering the most path.

Towers live in towers.json and evolution.json, monsters and abilities in monsters.json,
unlock cards in unlocks.json; all are read at startup, so the game can be rebalanced
without touching the code.

Every level writes a balance log (damage per tower, damage taken per enemy, waves,
economy, fusions...) to logs/<session>/ as JSON; see balance_log.py. Run with
--no-log to turn this off, and with --monsters to start on the Monsters side.

Modules:
  main.py         the Game state machine (waves, fusing, runs and passes, rewards, input,
                  logging hooks) and main()
  attack.py       the Monsters side (mixed into Game); attack_view.py draws it
  progress.py     the permanent profile: records, unlock cards, milestones
  towers.py       loads towers.json and evolution.json
  monsters.py     loads monsters.json
  levels.py       level themes and paths, wave generation and wave values
  entities.py     Enemy, Projectile, Tower: the combat rules, monster mechanics, abilities
  graphics.py     everything drawn on screen
  balance_log.py
"""

import json
import os
import random
import sys

import pygame

import graphics
from attack import DEFENDER_LIVES, AttackMixin
from attack_view import AttackView
from balance_log import LevelLog, LogSession
from entities import Enemy, Tower, cast_ability, heal_auras
from graphics import (BAD, GOLD, HEIGHT, MAP_H, MAP_W, PANEL_W, SCALES, TILE, Button, GameView, Popup, Ring,
                      CastWarning, Shards, mouse_pos, set_scale, tile_center, to_logical, window_size)
from levels import (BOSS_LEVELS, COLS, ENEMY_TYPES, LEVELS, ROWS, START_GOLD, START_LIVES, WAVES_PER_LEVEL,
                    build_path_cells, make_wave, wave_value)
from monsters import ABILITIES, BUDGET, REWARDS, UPGRADES
from progress import UNLOCKS, Profile, comp_snapshot, stronger
from towers import TOWER_ORDER, TOWERS, fusion_options

# --------------------------------------------------------------------------
# Rules (the rest are in levels.py and towers.py, the screen layout in graphics.py)
# --------------------------------------------------------------------------
FPS = 60
SPEEDS = (1, 2, 4, 10)  # game steps per frame
CAST_WARNING = 1.0  # seconds a replayed ability is shown before it lands
WAVE_LOCK = 1.0  # seconds after a level change before Space can send a wave (stops double presses)
FINALE_BOSS = "warden"  # joins the last wave of a Towers pass that ends early (see Game.finale)

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
SAVE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "savegame.json")
PROFILE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile.json")


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=1)
    except OSError as err:
        print(f"Could not save settings: {err}")


# --------------------------------------------------------------------------
# The run in progress, saved at the start of every level (see DESIGN.md)
# --------------------------------------------------------------------------
def load_save():
    """The run in progress as {"side", "pass", "levels_won", "monster_wins", "share_growth", "level", "gold", "lives",
    "layout", "upgrades", "escort", "finale"}, or None if there's no valid one. Saves from before passes existed count as
    pass 1 on the Towers side. lives are the defender's on the Monsters side; upgrades and escort are only used there.
    finale is [level, wave] (1-based) where a Towers pass ends early (see Game.finale), or None."""
    try:
        with open(SAVE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        level, gold, lives = data["level"], data["gold"], data["lives"]
        side, pass_no = data.get("side", "towers"), data.get("pass", 1)
        levels_won, monster_wins = data.get("levels_won", level), data.get("monster_wins", 0)
        numbers = (level, gold, lives, pass_no, levels_won, monster_wins)
        if (not all(isinstance(v, int) for v in numbers) or not 0 <= level < len(LEVELS) or lives <= 0
                or side not in ("towers", "monsters") or pass_no < 1 or levels_won < 0 or monster_wins < 0):
            return None
        # towers whose kind no longer exists in towers.json are dropped
        layout = [{"kind": e["kind"], "spent": int(e["spent"]), "tile": tuple(int(v) for v in e["tile"][:2])}
                  for e in data["layout"] if e["kind"] in TOWERS]
        upgrades = {k: max(0, int(r)) for k, r in data.get("upgrades", {}).items() if k in UPGRADES}
        escort = max(0, int(data.get("escort", 0)))
        # saves from before record tiers: every win grew the share like a normal record
        share_growth = float(data.get("share_growth", monster_wins * REWARDS["normal"]["share"]))
        finale = data.get("finale")
        if finale is not None:
            finale = (int(finale[0]), int(finale[1]))
            if side != "towers" or not level < finale[0] <= len(LEVELS) or not 1 <= finale[1] <= WAVES_PER_LEVEL:
                finale = None  # doesn't fit this pass (or the level count changed): the full pass
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return {"side": side, "pass": pass_no, "levels_won": levels_won, "monster_wins": monster_wins,
            "share_growth": share_growth, "level": level, "gold": gold, "lives": lives, "layout": layout,
            "upgrades": upgrades, "escort": escort, "finale": finale}


def write_save(save):
    try:
        tmp = SAVE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({**save, "layout": [{**e, "tile": list(e["tile"])} for e in save["layout"]]}, f, indent=1)
        os.replace(tmp, SAVE_FILE)  # never leaves a half-written save behind
    except OSError as err:
        print(f"Could not save the game: {err}")


def delete_save():
    try:
        os.remove(SAVE_FILE)
    except FileNotFoundError:
        pass
    except OSError as err:
        print(f"Could not delete the save: {err}")


# --------------------------------------------------------------------------
# Game
# --------------------------------------------------------------------------
def spec_snapshot():
    """Tower and enemy stats without drawing details, stored in every balance log."""
    return {"towers": {k: {f: v for f, v in s.items() if f not in ("look", "color")} for k, s in TOWERS.items()},
            "enemies": {k: {f: v for f, v in s.items() if f not in ("color", "inner", "shape", "sides", "size")}
                        for k, s in ENEMY_TYPES.items()}}


class Game(AttackMixin, AttackView, GameView):
    def __init__(self, screen, log_dir=LOG_DIR, side="towers"):
        """`side` is who the player plays: "towers" (build and defend) or "monsters" (attack.py)."""
        self.screen = screen
        self.side = side
        self.log_session = LogSession(log_dir) if log_dir else None
        self.log = None
        self.show_settings = False
        self.confirm_quit = False
        self.ambient = load_settings().get("ambient", True) is not False  # the Ambient effects setting
        self.save = load_save()
        self.profile = Profile.load(PROFILE_FILE)
        self.picking_side = False  # the new-run screen: choose Towers or Monsters
        self.side_chosen = False  # this launch already chose how to start (side pick or Continue)
        self.build_view()

        x = MAP_W + 12
        w = PANEL_W - 24
        third = (w - 8) // 3
        self.tower_buttons = {k: Button((x, 196 + i * 58, w, 52), k) for i, k in enumerate(TOWER_ORDER)}
        self.sell_button = Button((x, 470, w, 36), "Sell")
        self.rebuild_button = Button((x, 470, w, 36), "Rebuild")  # shown in the Sell spot when nothing is selected
        self.wave_button = Button((x, HEIGHT - 98, w, 40), "Next wave")
        self.speed_button = Button((x, HEIGHT - 50, third, 38), "Speed")
        self.pause_button = Button((x + third + 4, HEIGHT - 50, third, 38), "Pause")
        self.tree_button = Button((x + 2 * (third + 4), HEIGHT - 50, third, 38), "Tree")
        self.reset()

    # ---- state ------------------------------------------------------------
    def reset(self):
        self.new_run(self.side)

    def new_run(self, side):
        """Level 1 of pass 1 on `side`, with nothing won yet."""
        gold, lives = self.pass_start_purse()
        self.start_run(0, gold, DEFENDER_LIVES if side == "monsters" else lives, side=side)

    def pass_start_purse(self):
        """Gold and lives at the start of a Towers pass, tower cards included."""
        cards = self.profile.tower_mods()
        return START_GOLD + cards["gold"], START_LIVES + cards["lives"]

    def continue_game(self):
        """Start the saved level over, with the gold, lives and towers to rebuild it had when reached."""
        if self.save:
            self.side_chosen = True
            s = self.save
            self.start_run(s["level"], s["gold"], s["lives"], s["layout"], s["side"], s["pass"], s["levels_won"],
                           s["monster_wins"], s["upgrades"], s["escort"], s["share_growth"], s["finale"])
            self.untouched = False

    def start_run(self, idx, gold, lives, layout=(), side="towers", pass_no=1, levels_won=0, monster_wins=0,
                  upgrades=None, escort=0, share_growth=0.0, finale=None):
        self.finish_log("abandoned")
        if self.log_session:
            self.log_session.run += 1
        self.side = side
        self.pass_no = pass_no
        self.levels_won = levels_won  # this run's score
        self.monster_wins = monster_wins  # Monsters levels won this run
        self.share_growth = share_growth  # what those wins added to the budget share (attack.py)
        # (level, wave), 1-based: where the Monsters pass was won. The Towers pass after it ends on that wave,
        # with the Warden joining it (None: the full pass). Set on the Monsters side, used on the Towers side.
        self.finale = finale
        self.untouched = True  # nothing played yet: Continue is still on offer
        self.gold = gold
        self.start_attack_pass(upgrades, escort)
        self.lives = lives
        self.speed = 1
        self.paused = False
        self.show_tree = False
        self.load_level(idx)
        self.rebuild_layout = list(layout)

    def checkpoint(self, layout=()):
        """Save the run at the start of the current level."""
        self.save = {"side": self.side, "pass": self.pass_no, "levels_won": self.levels_won,
                     "monster_wins": self.monster_wins, "share_growth": self.share_growth, "level": self.level_idx,
                     "gold": self.gold, "lives": self.lives,
                     "layout": list(layout), "upgrades": dict(self.upgrades), "escort": self.escort,
                     "finale": list(self.finale) if self.finale else None}
        write_save(self.save)

    def level_won(self):
        self.levels_won += 1
        self.profile.note_run(self.levels_won)

    def run_over(self):
        """A level was lost: the run ends. The save goes; the profile (records, unlocks) stays."""
        self.state = "game_over"
        self.aiming = None
        self.finish_log("lost")
        self.profile.note_run(self.levels_won)
        self.save = None
        delete_save()

    def end_run(self):
        """After the run-over screen: a new run, on a side of the player's choice once that's unlocked."""
        if self.profile.milestones["monsters_side"]:
            self.picking_side = True
        else:
            self.new_run("towers")

    def pick_side(self, side):
        self.picking_side = False
        self.side_chosen = True
        self.new_run(side)

    def next_pass(self):
        """The pass is won: switch sides and start level 1 again, facing the records just set. A Towers pass
        keeps the finale the Monsters pass set; a Monsters pass has none."""
        self.side = "monsters" if self.side == "towers" else "towers"
        self.pass_no += 1
        if self.side == "towers":
            self.gold, self.lives = self.pass_start_purse()
        else:
            self.finale = None
            self.start_attack_pass()
        self.load_level(0)
        self.wave_lock = WAVE_LOCK
        self.checkpoint()

    def load_level(self, idx):
        self.clock = 0.0  # game time in this level; unaffected by pauses, sped up by the speed setting
        self.level_idx = idx
        self.theme, self.waypoints = LEVELS[idx]
        self.path_pts = [tile_center(x, y) for x, y in self.waypoints]
        self.path_cells = build_path_cells(self.waypoints)
        self.build_map()
        self.towers = {}
        self.enemies = []
        self.projectiles = []
        self.effects = []
        self.popups = []
        self.wave_idx = 0
        self.spawn_queue = []
        self.spawn_timer = 0.0
        self.hp_mult = 1.0
        self.state = "build"  # build | wave | level_complete | game_over | victory
        self.banner_timer = 3.5 if self.is_boss_level else 3.0
        self.boss_alert = 0.0
        self.wave_lock = 0.0
        self.rebuild_layout = []  # towers refunded at the end of the last level: {"kind", "spent", "tile"}
        self.build_kind = None
        self.selected = None
        self.dragging = None
        self.choice = None  # (tower, [kind, kind]) while the player picks a branch
        self.strongest_comp = None  # the most valuable set of towers on the map this level (progress.comp_snapshot)
        self.comps_by_wave = {}  # wave number -> the same, for that wave's window (see check_comp)
        self.wave_mods = {}  # monster modifiers for the current wave (entities.Enemy)
        self.card_mods = self.profile.tower_mods()  # the player's tower cards (towers.NO_TOWER_MODS)
        self.reward_cards = []  # card ids on offer after a win (see offer_rewards)
        self.reward_pool = None
        self.reward_tier = "normal"  # the record tier the cards on offer were drawn for
        self.starter_picks = None  # Monsters side, first time: starter cards still to offer
        self.wave_started_at = 0.0
        self.replay = []  # Towers side: recorded ability casts still to come this wave
        self.aiming, self.queue, self.budget, self.cooldowns = None, [], 0, {}  # Monsters side (attack.py)
        self.lives_at_start = self.lives
        self.pace_bonus = 0.0  # Monsters side: set by setup_attack_level
        if self.log_session:
            path_length = sum(a.distance_to(b) for a, b in zip(self.path_pts, self.path_pts[1:]))
            self.log = LevelLog(self.log_session, idx + 1, self.theme.name, self.is_boss_level, path_length,
                                self.lives, self.gold, spec_snapshot(), self.side)
        if self.side == "monsters":
            self.setup_attack_level()
        self.record_ratio = self.record_strength()
        self.record_tier = self.tier_for(self.record_ratio)
        self.log_event("record", ratio=round(self.record_ratio, 2), tier=self.record_tier,
                       share=round(self.share, 3) if self.side == "monsters" else None,
                       pace=round(self.pace_bonus, 3) if self.side == "monsters" else None)

    # ---- record strength ---------------------------------------------------
    def record_strength(self):
        """How strong this level's record is against par (what its generated waves are worth): on the
        Monsters side the defender's strongest comp, on the Towers side the monster waves faced (the
        generated ones where there's no record), added up."""
        par = sum(wave_value(self.level_idx, w) for w in range(WAVES_PER_LEVEL))
        if self.side == "monsters":
            strength = max((c["value"] for c in self.defender_record.values()), default=0)
        else:
            record = self.profile.monster_record(self.level_idx + 1)
            strength = sum(record[w]["value"] if w in record else wave_value(self.level_idx, w - 1)
                           for w in range(1, WAVES_PER_LEVEL + 1))
        return strength / par

    def tier_for(self, ratio):
        """weak, normal or strong, from the thresholds for this side in monsters.json."""
        weak_below, strong_from = REWARDS["tiers"][self.side]
        return "weak" if ratio < weak_below else "strong" if ratio >= strong_from else "normal"

    # ---- balance log ------------------------------------------------------
    def log_event(self, event_type, **data):
        if self.log:
            self.log.event(self.clock, event_type, **data)

    def finish_log(self, outcome):
        """Write the current level's log (once). A level quit before any wave isn't worth a file."""
        if not self.log or self.log.written or (outcome in ("quit", "abandoned") and not self.log.waves):
            return None
        for t in self.towers.values():
            self.log.add_tower(t)
        if self.side == "towers":
            self.check_comp("level_end")
        path = self.log.finish(outcome, self.clock, self.lives, self.gold, self.strongest_comp, self.comps_by_wave)
        print(f"Balance log written: {path}")
        return path

    def check_comp(self, trigger):
        """Keep the towers on the map as the level's strongest comp, and as the current wave's, where
        they beat what's stored (a tie keeps the earlier one).

        A wave's window runs from the end of the previous wave to the end of this one, so the build
        phase counts toward the wave it prepares for. The value on the map only drops when a tower is
        sold (buying adds to it, fusing and moving keep it), so checking just before every sell and
        when a window closes finds every peak."""
        if not self.towers:
            return
        wave = min(self.wave_idx + (self.state == "build"), WAVES_PER_LEVEL)
        comp = comp_snapshot(self.towers.values(), self.clock, trigger, wave, self.state == "wave")
        if stronger(comp, self.strongest_comp):
            self.strongest_comp = comp
        if stronger(comp, self.comps_by_wave.get(wave)):
            self.comps_by_wave[wave] = comp

    def register_enemy(self, enemy, origin):
        enemy.origin = origin
        enemy.wave = self.wave_idx
        enemy.spawn_t = self.clock
        self.enemies.append(enemy)
        if self.log:
            self.log.enemies.append(enemy)
            if origin != "wave":
                self.log.current_wave()["summoned"] += 1

    @property
    def finale_on(self):
        """Whether this pass ends early, on the wave its Monsters pass was won (Towers side only)."""
        return self.side == "towers" and self.finale is not None

    @property
    def last_level_idx(self):
        """Index of the level that ends this pass."""
        return self.finale[0] - 1 if self.finale_on else len(LEVELS) - 1

    @property
    def level_waves(self):
        """Waves in the current level: fewer on a finale's level, which ends on the finale wave."""
        return self.finale[1] if self.finale_on and self.level_idx == self.last_level_idx else WAVES_PER_LEVEL

    @property
    def level_boss(self):
        """The boss that joins this level's last wave, or None: a finale's level gets FINALE_BOSS."""
        if self.finale_on and self.level_idx == self.last_level_idx:
            return FINALE_BOSS
        return BOSS_LEVELS.get(self.level_idx + 1)

    @property
    def is_boss_level(self):
        return self.level_boss is not None

    @property
    def can_continue(self):
        """Continue (the saved run) is offered until something is played in the run on screen."""
        return self.save is not None and self.untouched and self.state == "build" and self.wave_idx == 0

    @property
    def can_rebuild(self):
        """Whether the Rebuild button shows (in the Sell button's spot, so only with nothing selected)."""
        return bool(self.rebuild_layout) and self.state in ("build", "wave") and not self.selected

    @property
    def frozen(self):
        return (self.paused or self.show_tree or self.show_settings or self.confirm_quit or self.choice is not None
                or bool(self.reward_cards) or self.picking_side)

    # ---- unlock cards -------------------------------------------------------
    def offer_rewards(self, side_won, tier="normal"):
        """After a win: cards from that side's pool to pick one from (if it gives cards yet). How many, and
        whether one is a sure rare, depends on the record's tier (the starter pack counts as normal)."""
        spec = REWARDS[tier]
        self.reward_tier = tier
        self.reward_pool = self.profile.reward_side(side_won)
        self.reward_cards = (self.profile.draw_cards(self.reward_pool, random, spec["cards"], spec["rare"])
                             if self.reward_pool else [])

    def pick_reward(self, index):
        card = self.reward_cards[index]
        self.profile.unlock(self.reward_pool, card)
        self.log_event("unlock", pool=self.reward_pool, card=card, rank=self.profile.rank(self.reward_pool, card),
                       offered=self.reward_cards, tier=self.reward_tier)
        self.popups.append(Popup((MAP_W / 2, MAP_H / 2 + 120), f"Unlocked: {UNLOCKS[self.reward_pool][card]['name']}",
                                 GOLD))
        self.reward_cards = []
        if self.starter_picks is not None:
            self.offer_starter_pick()
            if self.starter_picks <= 0 and not self.reward_cards:
                self.starter_picks = None

    def next_level(self):
        self.untouched = False
        if self.side == "monsters":
            self.load_level(self.level_idx + 1)
            self.wave_lock = WAVE_LOCK
            self.checkpoint()
            return
        # The map changes, so every tower is refunded at full price; Rebuild can buy them back.
        layout = [{"kind": t.kind, "spent": t.spent, "tile": t.tile} for t in self.towers.values()]
        self.gold += sum(t.spent for t in self.towers.values())
        self.load_level(self.level_idx + 1)
        self.rebuild_layout = layout
        self.wave_lock = WAVE_LOCK
        self.checkpoint(layout)

    def rebuild(self):
        """Buy back the last level's towers, most expensive first, each on the free tile covering the
        most path within its range (ties go to the tile closest to where it stood). Towers that can't
        be afforded or placed stay on the list for later."""
        if self.state not in ("build", "wave") or not self.rebuild_layout:
            return
        path = [tile_center(*c) for c in self.path_cells]
        coverage = {}  # range -> {tile: path cells in range}
        left, placed = [], 0
        for entry in sorted(self.rebuild_layout, key=lambda e: -e["spent"]):
            rng = TOWERS[entry["kind"]]["range"]
            if rng not in coverage:
                coverage[rng] = {(tx, ty): sum(1 for p in path if p.distance_to(tile_center(tx, ty)) <= rng)
                                 for tx in range(COLS) for ty in range(ROWS)}
            free = [tile for tile in coverage[rng] if self.is_free(tile)]
            if self.gold < entry["spent"] or not free:
                left.append(entry)
                continue
            ox, oy = entry["tile"]
            tile = max(free, key=lambda t: (coverage[rng][t], -((t[0] - ox) ** 2 + (t[1] - oy) ** 2)))
            tower = Tower(entry["kind"], tile, entry["spent"])
            tower.mods = self.card_mods
            self.gold -= tower.spent
            tower.history.append({"t": round(self.clock, 2), "event": "rebuilt", "kind": tower.kind})
            if self.log:
                self.log.add_tower(tower)
                self.log.spent["towers"] += tower.spent
            self.log_event("rebuild", tower=tower.uid, kind=tower.kind, tile=list(tile), cost=tower.spent)
            self.towers[tile] = tower
            self.effects.append(Ring(tower.pos, 30, GOLD, 0.4))
            placed += 1
        self.rebuild_layout = left
        if placed:
            self.popups.append(Popup((MAP_W / 2, MAP_H / 2), f"Rebuilt {placed} tower{'s' * (placed > 1)}", GOLD))

    def start_wave(self):
        if self.state == "build":
            self.untouched = False
        if self.side == "monsters":
            return self.send_wave()
        if self.state != "build" or self.wave_idx >= self.level_waves:
            return
        recorded = self.profile.monster_record(self.level_idx + 1).get(self.wave_idx + 1)
        if recorded:  # the player's own strongest wave from the Monsters side, abilities included
            self.spawn_queue = [k for k in recorded["queue"] if k in ENEMY_TYPES]
            self.hp_mult = recorded["hp_mult"]
            self.wave_mods = dict(recorded["mods"])
            self.replay = sorted((dict(c, warned=False) for c in recorded["casts"] if c["ability"] in ABILITIES),
                                 key=lambda c: c["t"])
            self.popups.append(Popup((MAP_W / 2, MAP_H / 2 - 40), "Your monsters' record attacks!", BAD))
        else:
            self.spawn_queue, self.hp_mult = make_wave(self.level_idx, self.wave_idx)
            self.wave_mods, self.replay = {}, []
        if self.finale_on and self.level_idx == self.last_level_idx and self.wave_idx + 1 == self.level_waves:
            # the wave the Monsters pass was won on, and the Warden with it
            self.spawn_queue = [k for k in self.spawn_queue if "boss" not in ENEMY_TYPES[k]] + [FINALE_BOSS]
        self.wave_mods["armor"] = self.card_mods["armor"]
        self.wave_idx += 1
        self.spawn_timer = 0.0
        self.wave_started_at = self.clock
        self.state = "wave"
        if self.log:
            self.log.start_wave(self.clock, self.wave_idx, self.hp_mult, self.spawn_queue, self.lives, self.gold)

    def is_free(self, tile):
        tx, ty = tile
        return 0 <= tx < COLS and 0 <= ty < ROWS and tile not in self.path_cells and tile not in self.towers

    def can_place(self, tile):
        """A new tower can go on a free tile, or straight onto a tower it can fuse with."""
        if self.gold < TOWERS[self.build_kind]["cost"]:
            return False
        other = self.towers.get(tile)
        if other:
            return bool(fusion_options(self.build_kind, other.kind))
        return self.is_free(tile)

    def place_tower(self, tile):
        tower = Tower(self.build_kind, tile)
        tower.mods = self.card_mods
        self.gold -= tower.spent
        other = self.towers.get(tile)
        tower.history.append({"t": round(self.clock, 2), "event": "bought", "kind": tower.kind})
        if self.log:
            self.log.add_tower(tower)
            self.log.spent["towers"] += tower.spent
        self.log_event("buy", tower=tower.uid, kind=tower.kind, tile=list(tile), cost=tower.spent,
                       onto=other.uid if other else None)
        if other:
            self.fuse(tower, other)
        else:
            self.towers[tile] = tower
        if self.gold < TOWERS[self.build_kind]["cost"]:
            self.build_kind = None

    def fuse(self, tower, target):
        """Merge `tower` into `target`, which keeps its spot. Branching fusions ask the player to choose."""
        options = tower.fusion_options(target)
        if self.towers.get(tower.tile) is tower:
            del self.towers[tower.tile]
        target.spent += tower.spent
        self.selected = target
        tower.status = f"fused_into:{target.uid}"
        tower.history.append({"t": round(self.clock, 2), "event": "fused_into", "tower": target.uid})
        if self.log:
            self.log.add_tower(target)
        self.log_event("fuse", consumed=tower.uid, consumed_kind=tower.kind, target=target.uid,
                       target_kind=target.kind, options=options)
        if len(options) == 1:
            self.evolve(target, options[0])
        else:
            self.choice = (target, options)
            self.build_kind = None

    def evolve(self, tower, kind):
        tower.history.append({"t": round(self.clock, 2), "event": "evolved", "from": tower.kind, "to": kind})
        self.log_event("evolve", tower=tower.uid, frm=tower.kind, to=kind, tier=TOWERS[kind]["tier"])
        tower.kind = kind
        tower.cooldown = 0.0
        self.effects.append(Ring(tower.pos, 36, GOLD, 0.45))
        self.popups.append(Popup(tower.pos, tower.spec["name"] + "!", GOLD))

    def choose(self, index):
        tower, options = self.choice
        self.choice = None
        self.log_event("branch_choice", tower=tower.uid, options=options, chosen=options[index])
        self.evolve(tower, options[index])

    def drop_dragged(self, pos):
        """Finish a drag: move the tower to a free tile or fuse it with a matching tower."""
        t, self.dragging = self.dragging, None
        if t is None or self.towers.get(t.tile) is not t or pos[0] >= MAP_W:
            return
        tile = (pos[0] // TILE, pos[1] // TILE)
        other = self.towers.get(tile)
        if other is t:
            return
        if other:
            if t.fusion_options(other):
                self.fuse(t, other)
        elif self.is_free(tile):
            self.log_event("move", tower=t.uid, kind=t.kind, frm=list(t.tile), to=list(tile),
                           during_wave=self.state == "wave")
            del self.towers[t.tile]
            t.move_to(tile)
            self.towers[tile] = t

    def sell_selected(self):
        t = self.selected
        if t and self.side == "towers":
            self.check_comp("sell")  # the comp just before it shrinks
            t.status = "sold"
            t.history.append({"t": round(self.clock, 2), "event": "sold", "value": t.sell_value})
            self.log_event("sell", tower=t.uid, kind=t.kind, value=t.sell_value)
            if self.log:
                self.log.add_tower(t)
                self.log.earned["sells"] += t.sell_value
            self.gold += t.sell_value
            self.popups.append(Popup(t.pos, f"+{t.sell_value}", GOLD))
            del self.towers[t.tile]
            self.selected = None
            self.dragging = None

    # ---- update -----------------------------------------------------------
    def update(self, dt):
        # banners are read in real time, so they don't flash past at high speed
        self.banner_timer -= dt / self.speed
        self.boss_alert -= dt / self.speed
        self.wave_lock -= dt / self.speed
        self.effects = [e for e in self.effects if e.update(dt)]
        self.popups = [p for p in self.popups if p.update(dt)]
        if self.state not in ("build", "wave"):
            return
        self.clock += dt
        if self.state == "wave":
            for t in self.towers.values():
                t.stats[t.kind]["wave_seconds"] += dt
            if self.side == "monsters":
                self.tick_cooldowns(dt)
            else:
                self.replay_casts()

        if self.state == "wave" and self.spawn_queue:
            self.spawn_timer -= dt
            if self.spawn_timer <= 0:
                kind = self.spawn_queue.pop(0)
                self.register_enemy(Enemy(kind, self.path_pts, self.hp_mult, self.wave_mods), "wave")
                self.spawn_timer = ENEMY_TYPES[kind]["gap"]
                if "boss" in ENEMY_TYPES[kind]:
                    self.boss_alert = 3.0
                elif self.spawn_queue and "boss" in ENEMY_TYPES[self.spawn_queue[0]]:
                    self.spawn_timer = 4.0  # a breather before the boss walks in

        for e in self.enemies:
            e.update(dt)
        heal_auras(self.enemies, dt)
        self.summon_minions(dt)
        for t in self.towers.values():
            t.update(dt, self.enemies, self.projectiles, self.effects)
        for p in self.projectiles:
            p.update(dt, self.enemies, self.effects)
        self.projectiles = [p for p in self.projectiles if not p.done]

        wave_log = self.log.current_wave() if self.log else None
        splits = []
        for e in self.enemies:
            if e.alive:
                continue
            splits += [(child, e.kind) for child in e.split()]
            e.end_t = self.clock
            if e.escaped:
                lost = self.lives if e.spec.get("fatal") else e.spec["damage"]
                if self.side == "monsters":
                    lost = max(0, min(lost, self.lives_in_reach))
                self.lives -= lost
                self.effects.append(Ring(e.pos, 30, BAD, 0.4))
                if wave_log:
                    wave_log["leaks"] += 1
                    wave_log["lives_lost"] += lost
            else:
                self.effects.append(Shards(e.pos, e.spec["color"], e.spec["size"], e.spin))
                if self.side == "towers":
                    reward = e.spec["cost"]  # a monster is worth what it costs to draft
                    self.gold += reward
                    self.popups.append(Popup(e.pos, f"+{reward}", GOLD))
                    self.effects.append(Ring(e.pos, e.spec["size"] + 8, e.spec["color"], 0.3))
                    if wave_log:
                        wave_log["kills"] += 1
                        wave_log["kill_gold"] += reward
                        self.log.earned["kills"] += reward
        self.enemies = [e for e in self.enemies if e.alive]
        for child, parent in splits:
            self.register_enemy(child, f"split:{parent}")

        if self.side == "monsters":
            if self.lives <= 0:
                self.win_attack_level(pass_won=True)
            elif self.state == "wave" and not self.spawn_queue and not self.enemies:
                self.end_attack_wave()
        elif self.lives <= 0:
            self.lives = 0
            self.run_over()
        elif self.state == "wave" and not self.spawn_queue and not self.enemies:
            bonus = 20 + 5 * self.wave_idx
            self.gold += bonus
            if self.log:
                self.log.earned["wave_bonus"] += bonus
                self.log.end_wave(self.clock, self.lives, self.gold, bonus)
            self.popups.append(Popup((MAP_W / 2, MAP_H / 2), f"Wave cleared! +{bonus}", GOLD))
            self.projectiles.clear()
            self.check_comp("wave_end")  # closes this wave's window
            if self.wave_idx < self.level_waves:
                self.state = "build"
            else:
                self.state = "level_complete" if self.level_idx < self.last_level_idx else "victory"
                self.profile.record_towers(self.level_idx + 1, self.comps_by_wave, self.card_mods)
                if self.state == "victory":
                    self.profile.reach("monsters_side")
                self.level_won()
                self.offer_rewards("towers", self.record_tier)
                self.finish_log("cleared")

    def replay_casts(self):
        """Towers side: fire the recorded wave's abilities at their recorded time and place, each
        announced CAST_WARNING seconds ahead (a pulsing circle, or a shout for whole-wave ones)."""
        t = self.clock - self.wave_started_at
        for c in self.replay:
            spec = ABILITIES[c["ability"]]
            pos = pygame.Vector2(c["pos"]) if c["pos"] else None
            if not c["warned"] and t >= c["t"] - CAST_WARNING:
                c["warned"] = True
                if pos is not None:
                    self.effects.append(CastWarning(pos, spec["radius"], spec["color"], CAST_WARNING))
                else:
                    self.popups.append(Popup((MAP_W / 2, 80), f"{spec['name']} incoming!", spec["color"]))
            if t >= c["t"]:
                cast_ability(spec, pos, self.towers.values(), self.enemies, self.effects, self.card_mods["grounding"])
                self.log_event("ability", ability=c["ability"], wave=self.wave_idx, pos=c["pos"], replayed=True)
        self.replay = [c for c in self.replay if t < c["t"]]

    def summon_minions(self, dt):
        for boss in [e for e in self.enemies if e.alive and "summon" in e.spec]:
            boss.summon_timer -= dt
            if boss.summon_timer > 0:
                continue
            kind, count, interval = boss.spec["summon"]
            boss.summon_timer = interval
            for _ in range(count):
                minion = Enemy(kind, self.path_pts, boss.hp_mult, boss.mods)
                minion.follow(boss)
                self.register_enemy(minion, f"summon:{boss.kind}")
            self.effects.append(Ring(boss.pos, boss.spec["size"] + 30, boss.spec["color"], 0.5))

    # ---- input ------------------------------------------------------------
    def handle_event(self, event):
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            event = pygame.event.Event(event.type, {**event.dict, "pos": to_logical(event.pos)})
        if self.confirm_quit:
            self.handle_quit_event(event)
        elif self.show_settings:
            self.handle_settings_event(event)
        elif self.picking_side:
            self.handle_side_pick_event(event)
        elif self.reward_cards:
            self.handle_reward_event(event)
        elif self.choice:
            self.handle_choice_event(event)
        elif event.type == pygame.KEYDOWN:
            self.handle_key(event.key)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if self.show_tree:
                self.show_tree = False
            elif self.side == "monsters" and self.handle_attack_click(event.pos, event.button):
                pass
            elif event.button == 3:
                self.build_kind = None
                self.selected = None
                self.dragging = None
            elif event.button == 1:
                self.handle_click(event.pos)
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.drop_dragged(event.pos)

    def handle_choice_event(self, event):
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_1, pygame.K_2):
            self.choose(event.key - pygame.K_1)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i, rect in enumerate(self.choice_cards()):
                if rect.collidepoint(event.pos):
                    self.choose(i)

    def handle_side_pick_event(self, event):
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_1, pygame.K_2):
            self.pick_side(("towers", "monsters")[event.key - pygame.K_1])
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_o:
            self.show_settings = True
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for side, rect in self.side_pick_rects():
                if rect.collidepoint(event.pos):
                    self.pick_side(side)

    def handle_reward_event(self, event):
        if event.type == pygame.KEYDOWN and pygame.K_1 <= event.key < pygame.K_1 + len(self.reward_cards):
            self.pick_reward(event.key - pygame.K_1)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i, rect in enumerate(self.reward_card_rects()):
                if rect.collidepoint(event.pos):
                    self.pick_reward(i)
                    return

    def handle_quit_event(self, event):
        """Esc / Enter / Y confirms; any other key or a click keeps playing."""
        if event.type == pygame.KEYDOWN:
            self.confirm_quit = False
            if event.key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_y):
                pygame.event.post(pygame.event.Event(pygame.QUIT))  # main() writes the log and exits
        elif event.type == pygame.MOUSEBUTTONDOWN:
            self.confirm_quit = False

    def handle_settings_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_MINUS, pygame.K_EQUALS, pygame.K_PLUS):
                step = -1 if event.key in (pygame.K_LEFT, pygame.K_MINUS) else 1
                fitting = [k for k in SCALES if self.scale_fits(k)]
                i = fitting.index(graphics.SCALE) if graphics.SCALE in fitting else 0
                self.apply_scale(fitting[max(0, min(len(fitting) - 1, i + step))])
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE, pygame.K_ESCAPE, pygame.K_o):
                self.close_settings()
            elif event.key == pygame.K_c and self.can_continue:
                self.continue_game()  # first, so closing the settings doesn't ask for a side
                self.close_settings()
            elif event.key == pygame.K_a:
                self.toggle_ambient()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for scale, rect in self.scale_buttons():
                if rect.collidepoint(event.pos) and self.scale_fits(scale):
                    self.apply_scale(scale)
            if self.ambient_button().collidepoint(event.pos):
                self.toggle_ambient()
            if self.settings_close_button().collidepoint(event.pos):
                self.close_settings()
            elif self.can_continue and self.settings_continue_button().collidepoint(event.pos):
                self.continue_game()
                self.close_settings()

    def toggle_ambient(self):
        """The Ambient effects setting: drifting particles and the glow's pulse. Saved straight away."""
        self.ambient = not self.ambient
        save_settings({**load_settings(), "ambient": self.ambient})

    def close_settings(self):
        self.show_settings = False
        if self.untouched and not self.side_chosen and self.profile.milestones["monsters_side"]:
            self.picking_side = True  # a new run, and the Monsters side is open: pick one
        settings = load_settings()
        if settings.get("scale") != graphics.SCALE:
            save_settings({**settings, "scale": graphics.SCALE})

    def handle_key(self, key):
        if key == pygame.K_o:
            self.show_settings = True
        elif key == pygame.K_t:
            self.show_tree = not self.show_tree
        elif self.show_tree:
            if key == pygame.K_ESCAPE:
                self.show_tree = False
        elif self.side == "monsters" and self.handle_attack_key(key):
            pass
        elif self.side == "monsters" and key in (pygame.K_b, pygame.K_s):
            pass  # nothing to rebuild or sell on the Monsters side
        elif key == pygame.K_r and self.state == "game_over":
            self.end_run()
        elif key == pygame.K_c and self.can_continue:
            self.continue_game()
        elif key == pygame.K_b:
            self.rebuild()
        elif key == pygame.K_SPACE:
            self.advance()
        elif key == pygame.K_p:
            self.paused = not self.paused
        elif key == pygame.K_f:
            self.cycle_speed(-1 if pygame.key.get_mods() & pygame.KMOD_SHIFT else 1)
        elif key == pygame.K_ESCAPE:
            if not (self.build_kind or self.selected or self.dragging):
                self.confirm_quit = True
            self.build_kind = None
            self.selected = None
            self.dragging = None
        elif key == pygame.K_s:
            self.sell_selected()
        elif pygame.K_1 <= key <= pygame.K_3:
            self.pick_tower(TOWER_ORDER[key - pygame.K_1])

    def cycle_speed(self, step):
        self.speed = SPEEDS[(SPEEDS.index(self.speed) + step) % len(SPEEDS)]

    def advance(self):
        if self.state == "build":
            if self.wave_lock <= 0:  # a quick second press after "Next level" must not send a wave
                self.start_wave()
        elif self.state == "level_complete":
            self.next_level()
        elif self.state == "victory":
            self.next_pass()
        elif self.state == "game_over":
            self.end_run()

    def pick_tower(self, kind):
        if self.build_kind == kind:
            self.build_kind = None
        elif self.gold >= TOWERS[kind]["cost"]:
            self.build_kind = kind
            self.selected = None

    def handle_click(self, pos):
        if pos[0] < MAP_W:
            if self.state in ("level_complete", "game_over", "victory"):
                self.advance()
                return
            tile = (pos[0] // TILE, pos[1] // TILE)
            if self.build_kind:
                if self.can_place(tile):
                    self.place_tower(tile)
            else:
                self.selected = self.dragging = self.towers.get(tile)
            return
        for kind, b in self.tower_buttons.items():
            if b.rect.collidepoint(pos) and self.side == "towers":
                self.pick_tower(kind)
        if self.sell_button.rect.collidepoint(pos) and self.selected and self.side == "towers":
            self.sell_selected()
        elif self.rebuild_button.rect.collidepoint(pos) and self.can_rebuild:
            self.rebuild()
        elif self.wave_button.rect.collidepoint(pos):
            self.advance()
        elif self.speed_button.rect.collidepoint(pos):
            self.cycle_speed(1)
        elif self.pause_button.rect.collidepoint(pos):
            self.paused = not self.paused
        elif self.tree_button.rect.collidepoint(pos):
            self.show_tree = True

    # ---- queries for the view --------------------------------------------
    def hovered_fusion(self):
        """(kind being fused, kind under the cursor, options) for the current drag or build, if any."""
        mx, my = mouse_pos()
        if mx >= MAP_W:
            return None
        other = self.towers.get((mx // TILE, my // TILE))
        if not other:
            return None
        if self.dragging and other is not self.dragging:
            return self.dragging.kind, other.kind, fusion_options(self.dragging.kind, other.kind)
        if self.build_kind:
            return self.build_kind, other.kind, fusion_options(self.build_kind, other.kind)
        return None


def main():
    pygame.init()
    # The saved scale, or the largest one below it that fits this screen.
    saved = load_settings().get("scale", 1.0)
    saved = saved if isinstance(saved, (int, float)) else 1.0
    set_scale(max([k for k in SCALES if k <= saved and Game.scale_fits(k)] or [1.0]))
    screen = pygame.display.set_mode(window_size())
    pygame.display.set_caption("Tower Defense")
    clock = pygame.time.Clock()
    side = "monsters" if "--monsters" in sys.argv else "towers"  # a debug shortcut until run flow lands
    game = Game(screen, log_dir=None if "--no-log" in sys.argv else LOG_DIR, side=side)
    game.show_settings = True  # start on the settings screen; Enter to play
    while True:
        dt = min(clock.tick(FPS) / 1000, 0.05)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                game.finish_log("quit")
                pygame.quit()
                sys.exit()
            game.handle_event(event)
        if not game.frozen:
            for _ in range(game.speed):
                game.update(dt)
        game.draw()
        pygame.display.flip()


if __name__ == "__main__":
    main()
