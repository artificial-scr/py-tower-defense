"""The Monsters side of the roguelike mode (see DESIGN.md), mixed into main.Game.

The towers are the player's tower record for the level: before wave w, the map is set to the
strongest comp they had during wave w. The player drafts each wave from a budget (the larger of
what the generated wave would have been worth and a share of that comp's value, a share that
grows with every Monsters level won in the run; whatever isn't spent carries over), sends it, and
uses abilities while it runs. Draining the defender's lives wins the level; if the towers are still
standing after the last wave, the run is over.

Controls on this side:
  1-9, 0       draft phase: draft that monster (Shift: 5); during a wave: use that ability
  Backspace    take the last monster off the queue (or click its icon on the map)
  Left click   on a panel row: draft / use it; on the map: cast an aimed ability, or see a
               tower's range
  Right click  cancel aiming (Esc too)
"""

import pygame

from entities import Tower, cast_ability
from graphics import MAP_W, TILE, Popup, tile_center
from levels import BOSS_LEVELS, LEVELS, WAVES_PER_LEVEL, wave_hp_mult, wave_value
from monsters import ABILITIES, BUDGET, ENEMY_TYPES
from towers import NO_TOWER_MODS

DEFENDER_LIVES = 20
QUEUE_MAX = 150  # monsters per wave; keeps very long waves (and frame times) in check
DRAFT_ROWS = 10  # monster kinds listed in the panel, and digit keys to draft them


class AttackMixin:
    # ---- level setup -------------------------------------------------------
    def setup_attack_level(self):
        """Called by load_level on the Monsters side."""
        self.lives = DEFENDER_LIVES
        self.budget = 0
        self.queue = []  # monster kinds drafted for the next wave, in spawn order
        self.aiming = None  # an area ability waiting for a click on the map
        self.ability_cooldowns = self.profile.abilities()  # ability -> cooldown after rank bonuses
        self.cooldowns = {k: 0.0 for k in self.ability_cooldowns}  # ability -> seconds until ready
        self.sent_waves = {}  # wave number -> the wave as it goes into the monster record
        self.wave_started_at = 0.0
        self.defender_record = self.profile.tower_record(self.level_idx + 1)
        self.prepare_draft()
        if not self.profile.milestones["starter_pack"]:
            self.starter_picks = int(BUDGET["starter_picks"])
            self.offer_starter_pick()

    @property
    def share(self):
        """The share of the defender's comp value the budget can claim (see monsters.json)."""
        return BUDGET["share_start"] + BUDGET["share_per_win"] * self.monster_wins

    def wave_budget(self, wave):
        """What drafting wave `wave` (1-based) adds to the budget, War Chest included."""
        comp = self.defender_comp(wave)
        base = max(wave_value(self.level_idx, wave - 1), self.share * (comp["value"] if comp else 0))
        return round(base * self.profile.budget_mult())

    def prepare_draft(self):
        """Before each wave: the defender takes its comp for that wave, and the budget grows."""
        self.place_defender(self.wave_idx + 1)
        self.budget += self.wave_budget(self.wave_idx + 1)

    def offer_starter_pick(self):
        """The first time on the Monsters side: a few unlock cards, one pick-1-of-3 screen at a time."""
        if self.starter_picks <= 0:
            self.profile.reach("starter_pack")
            return
        self.starter_picks -= 1
        self.offer_rewards("monsters")
        if not self.reward_cards:  # nothing left to unlock
            self.profile.reach("starter_pack")

    def defender_comp(self, wave):
        """The tower record's comp for a wave, or the latest one before it if that slot is empty."""
        for w in range(wave, 0, -1):
            if w in self.defender_record:
                return self.defender_record[w]
        return None

    def place_defender(self, wave):
        """Set the map to the defender's comp for a wave, with the tower cards it was recorded with."""
        comp = self.defender_comp(wave)
        self.towers = {}
        self.selected = None
        self.defender_mods = comp.get("mods", NO_TOWER_MODS) if comp else NO_TOWER_MODS
        for entry in comp["towers"] if comp else []:
            t = Tower(entry["kind"], tuple(entry["tile"]), entry["gold_spent"])
            t.mods = self.defender_mods
            t.history.append({"t": round(self.clock, 2), "event": "defending", "wave": wave})
            self.towers[t.tile] = t
            if self.log:
                self.log.add_tower(t)

    # ---- draft ---------------------------------------------------------------
    def draftable(self):
        """Kinds that can go into the next wave; a boss level's boss joins for its last wave."""
        kinds = self.profile.draftable()[:DRAFT_ROWS]
        if self.is_boss_level and self.wave_idx == WAVES_PER_LEVEL - 1:
            kinds.append(BOSS_LEVELS[self.level_idx + 1])
        return kinds

    def can_draft(self, kind):
        spec = ENEMY_TYPES[kind]
        return (self.state == "build" and kind in self.draftable() and self.budget >= spec["cost"]
                and len(self.queue) < QUEUE_MAX and not ("boss" in spec and kind in self.queue))

    def draft(self, kind, count=1):
        for _ in range(count):
            if not self.can_draft(kind):
                return
            self.queue.append(kind)
            self.budget -= ENEMY_TYPES[kind]["cost"]

    def undraft(self, index=-1):
        if self.state == "build" and self.queue:
            self.budget += ENEMY_TYPES[self.queue.pop(index)]["cost"]

    def send_wave(self):
        """Start the next wave with the drafted queue (an empty one is allowed: it saves the budget)."""
        if self.state != "build" or self.wave_idx >= WAVES_PER_LEVEL:
            return
        self.hp_mult = wave_hp_mult(self.level_idx, self.wave_idx)
        self.wave_mods = self.profile.monster_mods()
        self.spawn_queue = list(self.queue)
        fight_mods = {**self.wave_mods, "armor": self.defender_mods["armor"]}  # the defender's Piercing card
        self.wave_idx += 1
        self.sent_waves[self.wave_idx] = {"value": sum(ENEMY_TYPES[k]["cost"] for k in self.queue),
                                          "queue": list(self.queue), "hp_mult": self.hp_mult,
                                          "mods": dict(self.wave_mods), "casts": []}
        self.wave_mods = fight_mods
        self.queue = []
        self.spawn_timer = 0.0
        self.wave_started_at = self.clock
        self.state = "wave"
        if self.log:
            self.log.start_wave(self.clock, self.wave_idx, self.hp_mult, self.spawn_queue, self.lives, self.budget)

    # ---- abilities -------------------------------------------------------------
    def cast(self, ability, pos=None):
        """Use an ability; an area one without a position starts aiming (the next map click casts it)."""
        if self.state != "wave" or self.cooldowns.get(ability, 1) > 0:
            return
        spec = ABILITIES[ability]
        if spec["target"] == "area" and pos is None:
            self.aiming = None if self.aiming == ability else ability
            return
        self.aiming = None
        cast_ability(spec, pos, self.towers.values(), self.enemies, self.effects, self.defender_mods["grounding"])
        self.cooldowns[ability] = self.ability_cooldowns[ability]
        where = [round(pos[0]), round(pos[1])] if pos is not None else None
        self.sent_waves[self.wave_idx]["casts"].append(
            {"ability": ability, "t": round(self.clock - self.wave_started_at, 2), "pos": where})
        self.log_event("ability", ability=ability, wave=self.wave_idx, pos=where)

    def tick_cooldowns(self, dt):
        for k in self.cooldowns:
            self.cooldowns[k] = max(0.0, self.cooldowns[k] - dt)

    # ---- winning and losing ------------------------------------------------------
    def end_attack_wave(self):
        """A wave is over and the towers still stand: draft the next one, or the level is lost."""
        self.aiming = None
        if self.wave_idx < WAVES_PER_LEVEL:
            self.state = "build"
            self.prepare_draft()
            self.popups.append(Popup((MAP_W / 2, 300), f"Budget {self.budget}", (255, 210, 70)))
        else:
            self.run_over()

    def win_attack_level(self):
        """The defender is out of lives: the waves sent go into the monster record."""
        self.lives = 0
        self.aiming = None
        self.spawn_queue = []
        self.enemies = []
        self.projectiles = []
        self.profile.record_monsters(self.level_idx + 1, self.sent_waves)
        self.state = "level_complete" if self.level_idx + 1 < len(LEVELS) else "victory"
        if self.state == "victory":
            self.profile.reach("tower_cards")
        self.monster_wins += 1
        self.level_won()
        self.offer_rewards("monsters")
        self.finish_log("cleared")

    # ---- input --------------------------------------------------------------------
    def handle_attack_key(self, key):
        """Monsters-side keys; returns whether the key was used. Digits draft in the build phase and
        cast abilities during a wave; Backspace takes the last monster off the queue."""
        if pygame.K_1 <= key <= pygame.K_9 or key == pygame.K_0:
            i = 9 if key == pygame.K_0 else key - pygame.K_1
            if self.state == "build" and i < len(self.draftable()):
                self.draft(self.draftable()[i], 5 if pygame.key.get_mods() & pygame.KMOD_SHIFT else 1)
            elif self.state == "wave" and i < len(self.cooldowns):
                self.cast(list(self.cooldowns)[i])
            return True
        if key == pygame.K_BACKSPACE:
            self.undraft()
            return True
        if key == pygame.K_ESCAPE and self.aiming:
            self.aiming = None
            return True
        return False

    def handle_attack_click(self, pos, button):
        """Monsters-side clicks; returns whether the click was used."""
        if pos[0] < MAP_W:
            if self.aiming:
                if button == 1:
                    self.cast(self.aiming, pygame.Vector2(pos))
                else:
                    self.aiming = None
                return True
            for i, center in self.queue_icons():
                if center.distance_to(pos) <= 10:
                    self.undraft(i)
                    return True
            if button == 1 and self.state in ("build", "wave"):
                self.selected = self.towers.get((pos[0] // TILE, pos[1] // TILE))  # see a tower's range
                return True
            return False
        if button != 1:
            return False
        for key, rect in self.attack_rows():
            if rect.collidepoint(pos):
                if self.state == "build":
                    self.draft(key, 5 if pygame.key.get_mods() & pygame.KMOD_SHIFT else 1)
                else:
                    self.cast(key)
                return True
        return False

    # ---- queries for the view ---------------------------------------------------------
    def attack_rows(self):
        """(monster kind or ability, panel rect): the draft list in the build phase, abilities during a wave."""
        keys = self.draftable() if self.state == "build" else list(self.cooldowns) if self.state == "wave" else []
        return [(k, pygame.Rect(MAP_W + 12, 192 + i * 28, 196, 26)) for i, k in enumerate(keys)]

    def queue_icons(self):
        """(queue index, center) for the drafted monsters shown along the bottom of the map."""
        if self.state != "build":
            return []
        per_row = (MAP_W - 20) // 18
        return [(i, pygame.Vector2(20 + (i % per_row) * 18, tile_center(0, 15).y + 4 - (i // per_row) * 20))
                for i in range(len(self.queue))]
