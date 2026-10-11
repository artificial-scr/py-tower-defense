"""Drawing for the Monsters side (attack.py): the panel's draft list and ability bar, the queue
along the bottom of the map, and the aiming circle. Mixed into graphics.GameView.
"""

import pygame

from graphics import (BAD, GOLD, MAP_H, MAP_W, PANEL_LINE, TEXT, TEXT_DIM, draw_enemy_icon, mouse_pos, sdraw)
from levels import WAVES_PER_LEVEL
from monsters import ABILITIES, ENEMY_TYPES


class AttackView:
    def draw_attack_panel(self):
        x = MAP_W + 12
        self.draw_panel_header()
        self.text(self.font, f"Wave  {self.wave_idx} / {WAVES_PER_LEVEL}", TEXT, (x, 84))
        self.text(self.font, f"Towers' lives  {self.lives}", BAD if self.lives <= 5 else TEXT, (x, 110))
        self.text(self.font, f"Budget  {self.budget}", GOLD, (x, 136))
        self.text(self.font_s, f"claims {self.share:.0%} of their towers' value", TEXT_DIM, (x, 157))
        rows = self.attack_rows()
        mouse = mouse_pos()
        if self.state == "build":
            self.text(self.font_s, "DRAFT  (Shift: x5)", TEXT_DIM, (x, 176))
            for i, (kind, rect) in enumerate(rows):
                spec = ENEMY_TYPES[kind]
                ok = self.can_draft(kind)
                self.draw_row(rect, ok, rect.collidepoint(mouse), "boss" in spec)
                draw_enemy_icon(self.screen, spec, pygame.Vector2(rect.left + 14, rect.centery), 8)
                key = "" if i >= 10 else f"  [{(i + 1) % 10}]"
                self.text(self.font_s, spec["name"] + key, TEXT if ok else TEXT_DIM, (rect.left + 30, rect.centery),
                          "midleft")
                self.text(self.font_s, str(spec["cost"]), GOLD if ok else TEXT_DIM, (rect.right - 8, rect.centery),
                          "midright")
            value = sum(ENEMY_TYPES[k]["cost"] for k in self.queue)
            self.text(self.font_s, f"Queue: {len(self.queue)} monsters, worth {value}", TEXT, (x, 480))
            self.text(self.font_s, "Backspace / click icon: undo", TEXT_DIM, (x, 500))
        elif self.state == "wave":
            self.text(self.font_s, "ABILITIES", TEXT_DIM, (x, 176))
            if not rows:
                self.text(self.font_s, "None yet: win levels to", TEXT_DIM, (x, 196))
                self.text(self.font_s, "unlock some", TEXT_DIM, (x, 214))
            for i, (key, rect) in enumerate(rows):
                spec = ABILITIES[key]
                ready = self.cooldowns[key] <= 0
                self.draw_row(rect, ready, rect.collidepoint(mouse), self.aiming == key)
                if not ready:  # cooldown fills up from the left
                    done = 1 - self.cooldowns[key] / self.ability_cooldowns[key]
                    sdraw.rect(self.screen, spec["color"], (rect.left, rect.bottom - 4, rect.width * done, 3))
                sdraw.circle(self.screen, spec["color"], (rect.left + 14, rect.centery), 7)
                self.text(self.font_s, f"{spec['name']}  [{i + 1}]", TEXT if ready else TEXT_DIM,
                          (rect.left + 30, rect.centery), "midleft")
                label = "ready" if ready else f"{self.cooldowns[key]:.0f}s"
                self.text(self.font_s, label, GOLD if ready else TEXT_DIM, (rect.right - 8, rect.centery), "midright")
            if self.aiming:
                self.text(self.font_s, "Click the map to cast", GOLD, (x, 480))
                self.text(self.font_s, "Right click / Esc: cancel", TEXT_DIM, (x, 500))
        self.draw_panel_footer()

    def draw_row(self, rect, enabled, hover, active):
        bg = (70, 70, 85) if enabled and hover else (48, 48, 58) if enabled else (36, 36, 44)
        sdraw.rect(self.screen, bg, rect, border_radius=5)
        sdraw.rect(self.screen, GOLD if active else PANEL_LINE, rect, 2 if active else 1, border_radius=5)

    def draw_attack_map(self, fx):
        """The aiming circle (on the effects layer) and the drafted queue along the bottom of the map."""
        if self.aiming:
            mx, my = mouse_pos()
            if mx < MAP_W:
                spec = ABILITIES[self.aiming]
                sdraw.circle(fx, (*spec["color"], 50), (mx, my), spec["radius"])
                sdraw.circle(fx, (*spec["color"], 200), (mx, my), spec["radius"], 2)
        icons = self.queue_icons()
        if icons:
            top = min(c.y for _, c in icons) - 12
            sdraw.fill(fx, (0, 0, 0, 120), (0, top, MAP_W, MAP_H - top))
            for i, center in icons:
                draw_enemy_icon(fx, ENEMY_TYPES[self.queue[i]], center, 7)
