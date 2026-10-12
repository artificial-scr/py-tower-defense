"""Drawing for the Monsters side (attack.py): the panel's draft list, upgrades and ability bar, the
queue along the bottom of the map, and the aiming circle. Mixed into graphics.GameView.
"""

import pygame

from attack import DEFENDER_LIVES, ESCORT_KIND
from graphics import (BAD, GOLD, GOOD, MAP_H, MAP_W, PANEL_LINE, TEXT, TEXT_DIM, draw_enemy_icon, mouse_pos,
                      sdraw)
from levels import WAVES_PER_LEVEL
from monsters import ABILITIES, ENEMY_TYPES, UPGRADES


class AttackView:
    def draw_attack_panel(self):
        x = MAP_W + 12
        self.draw_panel_header()
        self.text(self.font, f"Wave  {self.wave_idx} / {WAVES_PER_LEVEL}", TEXT, (x, 78))
        self.text(self.font, f"Towers' lives  {max(self.lives, 0)} / {DEFENDER_LIVES}", TEXT, (x, 102))
        self.text(self.font_s, *self.pace_line(), (x, 124))
        self.text(self.font, f"Budget  {self.budget}", GOLD, (x, 146))
        claim = (f"claims {self.share:.0%} of tower value" if not round(self.pace_bonus, 2) else
                 f"claims {self.share:.0%}  ({self.pace_bonus:+.0%} for pace)")
        self.text(self.font_s, claim, TEXT_DIM, (x, 168))
        rows = self.attack_rows()
        mouse = mouse_pos()
        if self.state in ("build", "wave"):
            self.draw_upgrades(mouse)
        if self.state == "build":
            self.text(self.font_s, "DRAFT  (Shift: x5)", TEXT_DIM, (x, 188))
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
        elif self.state == "wave":
            self.text(self.font_s, "ABILITIES", TEXT_DIM, (x, 188))
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
                self.text(self.font_s, "Click the map to cast", GOLD, (x, 416))
                self.text(self.font_s, "Right click / Esc: cancel", TEXT_DIM, (x, 436))
        self.draw_panel_footer()

    def pace_line(self):
        """(text, color): what this level still needs from the defender's lives."""
        if self.levels_left == 0:
            return "Last level: take every life", BAD
        if self.lives_taken > 0:
            return f"-{self.lives_taken} here: cleared  ({self.levels_left} to go)", GOOD
        return f"Take 1 to clear  ({self.levels_left} to go)", TEXT_DIM

    def draw_upgrades(self, mouse):
        """Vitality / Stride / Plating: rank, key and the next rank's price. They can be bought (and a rank
        bought in this draft phase sold back) only while drafting."""
        for (key, rect), hotkey in zip(self.upgrade_buttons(), "QWE"):
            spec = UPGRADES[key]
            rank = self.upgrades[key]
            ok = self.can_upgrade(key)
            self.draw_row(rect, ok, rect.collidepoint(mouse), rank > 0)
            self.text(self.font_s, f"{spec['name']}", TEXT if ok else TEXT_DIM, (rect.centerx, rect.top + 3), "midtop")
            for i in range(spec["max"]):  # rank pips
                pip = pygame.Rect(rect.centerx - spec["max"] * 5 + i * 10 + 1, rect.top + 21, 8, 5)
                sdraw.rect(self.screen, GOLD if i < rank else PANEL_LINE, pip)
            if rank >= spec["max"]:
                label, color = "MAX", GOLD
            else:
                label, color = f"{self.upgrade_price(key)} [{hotkey}]", GOLD if ok else TEXT_DIM
            self.text(self.font_s, label, color, (rect.centerx, rect.bottom - 3), "midbottom")

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
        if self.state != "build":
            return
        top = self.queue_strip_top()
        sdraw.fill(fx, (0, 0, 0, 120), (0, top, MAP_W, MAP_H - top))
        for i, center in self.queue_icons():
            draw_enemy_icon(fx, ENEMY_TYPES[self.queue[i]], center, 7)

    def queue_strip_top(self):
        return min([c.y for _, c in self.queue_icons()], default=MAP_H - 8) - 30

    def draw_queue_text(self):
        """Over the queue strip (drawn after the effects layer, so the strip doesn't dim it)."""
        if self.state != "build":
            return
        top = self.queue_strip_top()
        value = sum(ENEMY_TYPES[k]["cost"] for k in self.queue)
        escort = self.escort_for_next_wave()
        line = f"Queue: {len(self.queue)} monsters, worth {value}"
        if escort:
            line += f"  +{escort} escort {ENEMY_TYPES[ESCORT_KIND]['name']}s"
        self.text(self.font_s, line, TEXT, (12, top + 4))
        self.text(self.font_s, "Backspace / click icon: undo   Right click upgrade: refund", TEXT_DIM,
                  (MAP_W - 12, top + 4), "topright")
