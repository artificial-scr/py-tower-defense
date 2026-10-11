"""A simple tower defense game built with pygame-ce.

Towers are never upgraded directly: they evolve by fusing.

  Tier 1  Gun, Cannon, Frost (bought from the panel)
  Tier 2  two identical tier 1 towers fuse into Rifle / Mortar / Chiller
  Tier 3  two identical tier 2 towers fuse, and you pick one of two branches
  Tier 4  two tier 3 towers from *different* lines fuse into one of 12 final,
          cross-type towers (press T in game to see the whole tree)

There are 20 levels, each with its own color theme and path. Levels 10 and 20
are boss levels: their last wave ends with a boss that summons minions, resists
slows, and costs the game if it gets through.

Controls
--------
1 / 2 / 3      pick a tower to build (Gun, Cannon, Frost)
Left click     place the picked tower / select an existing tower
Drag a tower   move it to any free tile, at any time; drop it on a tower it can
               fuse with to evolve it (dropping a bought tower works too)
Right click    cancel placement / deselect (Esc also works)
Esc            cancel / close; with nothing to cancel it asks to quit (Esc again quits)
S              sell the selected tower
T              show the evolution tree
Space          start the next wave (or continue to the next level)
F              cycle game speed: 1x, 2x, 4x, 10x (Shift+F goes back)
P              pause
O              settings (display scale); also shown at launch
R              restart after game over or victory

Tower stats and looks live in towers.json, the evolution tree in evolution.json; both
are read at startup, so towers can be rebalanced or added without touching the code.

Every level writes a balance log (damage per tower, damage taken per enemy, waves,
economy, fusions...) to logs/<session>/ as JSON; see balance_log.py. Run with
--no-log to turn this off.

Modules:
  main.py       the Game state machine (waves, fusing, input, logging hooks) and main()
  towers.py     loads towers.json and evolution.json
  levels.py     level themes and paths, enemy types, wave generation
  entities.py   Enemy, Projectile, Tower: the combat rules
  graphics.py   everything drawn on screen
  balance_log.py
"""

import json
import os
import sys

import pygame

import graphics
from balance_log import LevelLog, LogSession
from entities import Enemy, Tower
from graphics import (BAD, GOLD, HEIGHT, MAP_H, MAP_W, PANEL_W, SCALES, TILE, Button, GameView, Popup, Ring,
                      mouse_pos, render_map, set_scale, tile_center, to_logical, window_size)
from levels import (BOSS_LEVELS, COLS, ENEMY_TYPES, LEVELS, ROWS, START_GOLD, START_LIVES, WAVES_PER_LEVEL,
                    build_path_cells, make_wave)
from towers import TOWER_ORDER, TOWERS, fusion_options

# --------------------------------------------------------------------------
# Rules (the rest are in levels.py and towers.py, the screen layout in graphics.py)
# --------------------------------------------------------------------------
FPS = 60
SPEEDS = (1, 2, 4, 10)  # game steps per frame

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")


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
# Game
# --------------------------------------------------------------------------
def spec_snapshot():
    """Tower and enemy stats without drawing details, stored in every balance log."""
    return {"towers": {k: {f: v for f, v in s.items() if f not in ("look", "color")} for k, s in TOWERS.items()},
            "enemies": {k: {f: v for f, v in s.items() if f not in ("color", "inner", "shape", "sides", "size")}
                        for k, s in ENEMY_TYPES.items()}}


class Game(GameView):
    def __init__(self, screen, log_dir=LOG_DIR):
        self.screen = screen
        self.log_session = LogSession(log_dir) if log_dir else None
        self.log = None
        self.show_settings = False
        self.confirm_quit = False
        self.build_view()

        x = MAP_W + 12
        w = PANEL_W - 24
        third = (w - 8) // 3
        self.tower_buttons = {k: Button((x, 196 + i * 58, w, 52), k) for i, k in enumerate(TOWER_ORDER)}
        self.sell_button = Button((x, 470, w, 36), "Sell")
        self.wave_button = Button((x, HEIGHT - 98, w, 40), "Next wave")
        self.speed_button = Button((x, HEIGHT - 50, third, 38), "Speed")
        self.pause_button = Button((x + third + 4, HEIGHT - 50, third, 38), "Pause")
        self.tree_button = Button((x + 2 * (third + 4), HEIGHT - 50, third, 38), "Tree")
        self.reset()

    # ---- state ------------------------------------------------------------
    def reset(self):
        self.finish_log("abandoned")
        if self.log_session:
            self.log_session.run += 1
        self.gold = START_GOLD
        self.lives = START_LIVES
        self.speed = 1
        self.paused = False
        self.show_tree = False
        self.load_level(0)

    def load_level(self, idx):
        self.clock = 0.0  # game time in this level; unaffected by pauses, sped up by the speed setting
        self.level_idx = idx
        self.theme, self.waypoints = LEVELS[idx]
        self.path_pts = [tile_center(x, y) for x, y in self.waypoints]
        self.path_cells = build_path_cells(self.waypoints)
        self.map_surface = render_map(self.theme, self.waypoints)
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
        self.build_kind = None
        self.selected = None
        self.dragging = None
        self.choice = None  # (tower, [kind, kind]) while the player picks a branch
        if self.log_session:
            path_length = sum(a.distance_to(b) for a, b in zip(self.path_pts, self.path_pts[1:]))
            self.log = LevelLog(self.log_session, idx + 1, self.theme.name, self.is_boss_level, path_length,
                                self.lives, self.gold, spec_snapshot())

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
        path = self.log.finish(outcome, self.clock, self.lives, self.gold)
        print(f"Balance log written: {path}")
        return path

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
    def is_boss_level(self):
        return self.level_idx + 1 in BOSS_LEVELS

    @property
    def frozen(self):
        return self.paused or self.show_tree or self.show_settings or self.confirm_quit or self.choice is not None

    def next_level(self):
        # The map changes, so every tower is refunded at full price.
        self.gold += sum(t.spent for t in self.towers.values())
        self.load_level(self.level_idx + 1)

    def start_wave(self):
        if self.state != "build" or self.wave_idx >= WAVES_PER_LEVEL:
            return
        self.spawn_queue, self.hp_mult = make_wave(self.level_idx, self.wave_idx)
        self.wave_idx += 1
        self.spawn_timer = 0.0
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
        if t:
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
        self.effects = [e for e in self.effects if e.update(dt)]
        self.popups = [p for p in self.popups if p.update(dt)]
        if self.state not in ("build", "wave"):
            return
        self.clock += dt
        if self.state == "wave":
            for t in self.towers.values():
                t.stats[t.kind]["wave_seconds"] += dt

        if self.state == "wave" and self.spawn_queue:
            self.spawn_timer -= dt
            if self.spawn_timer <= 0:
                kind = self.spawn_queue.pop(0)
                self.register_enemy(Enemy(kind, self.path_pts, self.hp_mult), "wave")
                self.spawn_timer = ENEMY_TYPES[kind]["gap"]
                if "boss" in ENEMY_TYPES[kind]:
                    self.boss_alert = 3.0
                elif self.spawn_queue and "boss" in ENEMY_TYPES[self.spawn_queue[0]]:
                    self.spawn_timer = 4.0  # a breather before the boss walks in

        for e in self.enemies:
            e.update(dt)
        self.summon_minions(dt)
        for t in self.towers.values():
            t.update(dt, self.enemies, self.projectiles, self.effects)
        for p in self.projectiles:
            p.update(dt, self.enemies, self.effects)
        self.projectiles = [p for p in self.projectiles if not p.done]

        wave_log = self.log.current_wave() if self.log else None
        for e in self.enemies:
            if e.alive:
                continue
            e.end_t = self.clock
            if e.escaped:
                self.lives -= e.spec["damage"]
                self.effects.append(Ring(e.pos, 30, BAD, 0.4))
                if wave_log:
                    wave_log["leaks"] += 1
                    wave_log["lives_lost"] += e.spec["damage"]
            else:
                self.gold += e.spec["reward"]
                self.popups.append(Popup(e.pos, f"+{e.spec['reward']}", GOLD))
                self.effects.append(Ring(e.pos, e.spec["size"] + 8, e.spec["color"], 0.3))
                if wave_log:
                    wave_log["kills"] += 1
                    wave_log["kill_gold"] += e.spec["reward"]
                    self.log.earned["kills"] += e.spec["reward"]
        self.enemies = [e for e in self.enemies if e.alive]

        if self.lives <= 0:
            self.lives = 0
            self.state = "game_over"
            self.finish_log("lost")
        elif self.state == "wave" and not self.spawn_queue and not self.enemies:
            bonus = 20 + 5 * self.wave_idx
            self.gold += bonus
            if self.log:
                self.log.earned["wave_bonus"] += bonus
                self.log.end_wave(self.clock, self.lives, self.gold, bonus)
            self.popups.append(Popup((MAP_W / 2, MAP_H / 2), f"Wave cleared! +{bonus}", GOLD))
            self.projectiles.clear()
            if self.wave_idx < WAVES_PER_LEVEL:
                self.state = "build"
            else:
                self.state = "level_complete" if self.level_idx + 1 < len(LEVELS) else "victory"
                self.finish_log("cleared")

    def summon_minions(self, dt):
        for boss in [e for e in self.enemies if e.alive and "summon" in e.spec]:
            boss.summon_timer -= dt
            if boss.summon_timer > 0:
                continue
            kind, count, interval = boss.spec["summon"]
            boss.summon_timer = interval
            for _ in range(count):
                minion = Enemy(kind, self.path_pts, self.hp_mult)
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
        elif self.choice:
            self.handle_choice_event(event)
        elif event.type == pygame.KEYDOWN:
            self.handle_key(event.key)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if self.show_tree:
                self.show_tree = False
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
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for scale, rect in self.scale_buttons():
                if rect.collidepoint(event.pos) and self.scale_fits(scale):
                    self.apply_scale(scale)
            if self.settings_close_button().collidepoint(event.pos):
                self.close_settings()

    def close_settings(self):
        self.show_settings = False
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
        elif key == pygame.K_r and self.state in ("game_over", "victory"):
            self.reset()
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
            self.start_wave()
        elif self.state == "level_complete":
            self.next_level()
        elif self.state in ("game_over", "victory"):
            self.reset()

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
            if b.rect.collidepoint(pos):
                self.pick_tower(kind)
        if self.sell_button.rect.collidepoint(pos):
            self.sell_selected()
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
    game = Game(screen, log_dir=None if "--no-log" in sys.argv else LOG_DIR)
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
