"""The Monsters side of the roguelike mode (see DESIGN.md), mixed into main.Game.

The towers are the player's tower record for the level: before wave w, the map is set to the
strongest comp they had during wave w. The player drafts each wave from a budget (the larger of
what the generated wave would have been worth and a share of that comp's value; whatever isn't
spent carries over), sends it, and uses abilities while it runs. The share grows with every
Monsters level won in the run (more for stronger records, see main.Game.record_tier), and for each
level it's raised when the run is behind an even pace of lives taken and lowered when it's ahead.

The defender has DEFENDER_LIVES for the whole pass. A level is cleared by taking at least one of
them; the pass is won the moment the last one goes. A level that takes none, or reaching the end of
the last level with lives left, ends the run. The Towers pass that follows a won one ends on the
wave it was won on, with the Warden joining that wave (main.Game.finale): ending a pass early makes
the next one shorter but harder.

Stat upgrades (monsters.json) are bought with the budget and last for the rest of the pass. Each
purchase also sends Basics worth its price as an escort, at most escort_per_wave with each wave.

The controls on this side are listed in README.md (Controls).
"""

import pygame

from effects import Popup
from entities import Tower, cast_ability
from graphics import MAP_W, TILE
from levels import BOSS_LEVELS, LEVELS, WAVES_PER_LEVEL, wave_hp_mult, wave_value
from monsters import ABILITIES, BUDGET, ENEMY_TYPES, REWARDS, UPGRADES
from towers import NO_TOWER_MODS

DEFENDER_LIVES = 20  # for the whole pass
QUEUE_MAX = 150  # drafted monsters per wave; keeps very long waves (and frame times) in check
DRAFT_ROWS = 10  # monster kinds listed in the panel, and digit keys to draft them
UPGRADE_KEYS = (pygame.K_q, pygame.K_w, pygame.K_e)  # in monsters.json order
ESCORT_KIND = "basic"


class AttackMixin:
    # ---- pass and level setup ------------------------------------------------
    def start_attack_pass(self, upgrades=None, escort=0):
        """Pass-long state on the Monsters side: the defender's lives and the stat upgrades bought."""
        self.lives = DEFENDER_LIVES
        self.upgrades = {k: min(int((upgrades or {}).get(k, 0)), spec["max"]) for k, spec in UPGRADES.items()}
        self.escort = escort  # Basics still to send for upgrades bought (see buy_upgrade)

    def setup_attack_level(self):
        """Called by load_level on the Monsters side."""
        self.bought = []  # (upgrade, price) bought in this draft phase, which can still be sold back
        self.pace_bonus = self.pace_adjustment()
        self.budget = 0
        self.queue = []  # monster kinds drafted for the next wave, in spawn order
        self.aiming = None  # an area ability waiting for a click on the map
        self.ability_cooldowns = self.profile.abilities()  # ability -> cooldown after rank bonuses
        self.cooldowns = {k: 0.0 for k in self.ability_cooldowns}  # ability -> seconds until ready
        self.sent_waves = {}  # wave number -> the wave as it goes into the monster record
        self.wave_started_at = 0.0
        self.defender_record = self.profile.tower_record(self.level_idx + 1)
        self.level_budget = sum(self.wave_budget(w) for w in range(1, WAVES_PER_LEVEL + 1))
        self.prepare_draft()
        if not self.profile.milestones["starter_pack"]:
            self.starter_picks = int(BUDGET["starter_picks"])
            self.offer_starter_pick()

    @property
    def share(self):
        """The share of the defender's comp value the budget can claim (see monsters.json)."""
        return max(0.0, BUDGET["share_start"] + self.share_growth + self.pace_bonus)

    def pace_adjustment(self):
        """At the start of a level: pace_per_life for every life the run is behind an even pace (the
        defender's lives spread over the levels), negative when it's ahead; at most pace_max up and pace_min
        down."""
        expected = DEFENDER_LIVES * self.level_idx / len(LEVELS)
        behind = expected - (DEFENDER_LIVES - self.lives_at_start)
        return max(-BUDGET["pace_min"], min(BUDGET["pace_max"], BUDGET["pace_per_life"] * behind))

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
            self.note(t, "defending", wave=wave)
            self.towers[t.tile] = t

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

    # ---- stat upgrades ----------------------------------------------------------
    def upgrade_price(self, key):
        """The next rank's price: a share of this level's budget, times the rank."""
        return max(1, round(BUDGET["upgrade_price"] * (self.upgrades[key] + 1) * self.level_budget))

    def can_upgrade(self, key):
        return (self.state == "build" and self.upgrades[key] < UPGRADES[key]["max"]
                and self.budget >= self.upgrade_price(key))

    def buy_upgrade(self, key):
        """A rank of a stat upgrade for the rest of the pass, plus an escort of Basics worth its price."""
        if not self.can_upgrade(key):
            return
        price = self.upgrade_price(key)
        self.budget -= price
        self.upgrades[key] += 1
        self.escort += price // ENEMY_TYPES[ESCORT_KIND]["cost"]
        self.bought.append((key, price))
        self.log_event("upgrade", upgrade=key, rank=self.upgrades[key], price=price)

    def sell_upgrade(self, key):
        """Undo the latest rank of `key` bought in this draft phase."""
        for i in range(len(self.bought) - 1, -1, -1):
            if self.bought[i][0] == key and self.state == "build":
                price = self.bought.pop(i)[1]
                self.budget += price
                self.upgrades[key] -= 1
                self.escort -= price // ENEMY_TYPES[ESCORT_KIND]["cost"]
                self.log_event("upgrade_sold", upgrade=key, rank=self.upgrades[key], price=price)
                return

    def upgrade_mods(self):
        """Enemy modifiers from the monster cards and the upgrades bought (see entities.Enemy)."""
        mods = {**self.profile.monster_mods(), "armor_flat": 0}
        for key, rank in self.upgrades.items():
            spec = UPGRADES[key]
            if spec["stat"] == "armor":
                mods["armor_flat"] += spec["per_rank"] * rank
            else:
                mods[spec["stat"]] *= 1 + spec["per_rank"] * rank
        return mods

    def escort_for_next_wave(self):
        return min(self.escort, int(BUDGET["escort_per_wave"]))

    def send_wave(self):
        """Start the next wave with the escort and the drafted queue (an empty one is allowed: it saves the
        budget)."""
        if self.state != "build" or self.wave_idx >= WAVES_PER_LEVEL:
            return
        self.hp_mult = wave_hp_mult(self.level_idx, self.wave_idx)
        self.wave_mods = self.upgrade_mods()
        escort = self.escort_for_next_wave()
        self.escort -= escort
        self.bought = []
        self.spawn_queue = [ESCORT_KIND] * escort + self.queue
        fight_mods = {**self.wave_mods, "armor": self.defender_mods["armor"]}  # the defender's Piercing card
        self.wave_idx += 1
        self.sent_waves[self.wave_idx] = {"value": sum(ENEMY_TYPES[k]["cost"] for k in self.spawn_queue),
                                          "queue": list(self.spawn_queue), "hp_mult": self.hp_mult,
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
    @property
    def lives_taken(self):
        """Lives the defender has lost in this level."""
        return self.lives_at_start - max(self.lives, 0)

    @property
    def lives_in_reach(self):
        """How many more lives this level can take (see max_lives_per_level in monsters.json)."""
        cap = int(BUDGET["max_lives_per_level"])
        return min(self.lives, cap - self.lives_taken) if cap else self.lives

    @property
    def levels_left(self):
        """Levels after this one in the pass."""
        return len(LEVELS) - 1 - self.level_idx

    def end_attack_wave(self):
        """A wave is over and the towers still stand: draft the next one, or the level is over. It's
        cleared if it took a life, unless it was the last level (where every life had to go)."""
        self.aiming = None
        if self.wave_idx < WAVES_PER_LEVEL:
            self.state = "build"
            self.prepare_draft()
            self.popups.append(Popup((MAP_W / 2, 300), f"Budget {self.budget}", (255, 210, 70)))
        elif self.lives_taken > 0 and self.levels_left > 0:
            self.win_attack_level(pass_won=False)
        else:
            self.run_over()

    def win_attack_level(self, pass_won):
        """The level is cleared (pass_won: the defender is out of lives, which also wins the pass). The
        waves sent go into the monster record."""
        self.aiming = None
        if pass_won:
            self.lives = 0
            self.spawn_queue = []
            self.enemies = []
            self.projectiles = []
        self.profile.record_monsters(self.level_idx + 1, self.sent_waves)
        self.state = "victory" if pass_won else "level_complete"
        if pass_won:
            self.profile.reach("tower_cards")
            self.finale = (self.level_idx + 1, self.wave_idx)  # where the next Towers pass ends
        self.monster_wins += 1
        self.share_growth += REWARDS[self.record_tier]["share"]
        self.level_won()
        self.offer_rewards("monsters", self.record_tier)
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
        if key in UPGRADE_KEYS:
            if self.state == "build":
                self.buy_upgrade(list(UPGRADES)[UPGRADE_KEYS.index(key)])
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
        for key, rect in self.upgrade_buttons():
            if rect.collidepoint(pos):
                if button == 1:
                    self.buy_upgrade(key)
                elif button == 3:
                    self.sell_upgrade(key)
                return True
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
