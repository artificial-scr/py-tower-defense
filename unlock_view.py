"""Drawing for tower unlocks (achievements.py): the card for a tower (or secret boss) just unlocked, the
next unlock pinned in the panel, and the lock drawn over towers the player doesn't own yet. Mixed into
graphics.GameView, which uses these in the build panel, the branch choice and the evolution tree.
"""

import math
from itertools import pairwise

import pygame

import graphics
import sprites
from achievements import ACHIEVEMENTS, BOSS_ACHIEVEMENTS, UNLOCKED_BY, goal_key
from graphics import (
    CARD,
    GOLD,
    MAP_H,
    MAP_W,
    PANEL_LINE,
    PANEL_W,
    TEXT,
    TEXT_DIM,
    blit_center,
    draw_tower_shape,
    sdraw,
    sp,
    wrap,
)
from monsters import ENEMY_TYPES
from towers import CROSS, LINES, TOWERS

LOCK_SHADE = (16, 16, 22, 200)


def lock_image(radius):
    """A dark disc with a padlock on it, laid over a tower's picture."""
    img = pygame.Surface(sp((radius * 2, radius * 2)), pygame.SRCALPHA)
    c = pygame.Vector2(radius, radius)
    sdraw.circle(img, LOCK_SHADE, c, radius)
    sdraw.circle(img, TEXT_DIM, c - (0, 3), 5, 2)
    sdraw.rect(img, TEXT_DIM, (c.x - 7, c.y - 2, 14, 10), border_radius=2)
    return img


# ---- secret bosses' cards: art after the boss, behind the words --------------------------------
BOSS_CARD = (14, 14, 18)
EYE_RED = (255, 60, 50)


def silhouette(kind, size):
    """The boss's still picture (facing up), almost black: only its outline shows."""
    img = sprites.enemy_icon(kind, size, graphics.SCALE).copy()
    img.fill((12, 13, 12), special_flags=pygame.BLEND_RGB_MULT)
    return img


def glowing_eye(surf, pos, r, alpha, color=EYE_RED):
    sdraw.circle(surf, (*color, round(alpha * 0.25)), pos, r * 2.4)
    sdraw.circle(surf, (*color, round(alpha)), pos, r)


def lurker_art(surf, w, h, spec, kind, t):
    """Any secret boss without its own art: its outline in the dark, two eyes in its colour."""
    c = pygame.Vector2(w / 2, h / 2 + 8)
    blit_center(surf, silhouette(kind, 34), c)
    for k in (-1, 1):
        glowing_eye(surf, c + (k * 7, -24), 2.5, 200 + 55 * math.sin(t * 2))


def brood_art(surf, w, h, spec, kind, t):
    """The Brood Mother: a web across the dark, a young one letting itself down on a thread, egg sacs glowing
    in the corners, and her outline in the middle, the eight red eyes of her crown open (they blink)."""
    pale = spec["inner"][2]
    c = pygame.Vector2(w / 2, h * 0.42)
    spokes = [pygame.Vector2(1, 0).rotate(i * 30 + 8) for i in range(12)]
    for d in spokes:
        sdraw.line(surf, (*pale, 40), c, c + d * w, 1)
    for ring in range(1, 7):  # each thread sags a little toward the middle between two spokes
        r = ring * 26
        for a, b in zip(spokes, spokes[1:] + spokes[:1]):
            p, q = c + a * r, c + b * r
            mid = c + (p + q - 2 * c) / 2 * 0.9
            sdraw.line(surf, (*pale, 55 - ring * 6), p, mid, 1)
            sdraw.line(surf, (*pale, 55 - ring * 6), mid, q, 1)
    for corner, flip in (((26, h - 22), 1), ((w - 26, h - 22), -1)):  # egg sacs, swelling in turn
        for i, (x, y) in enumerate(((0, 0), (14, 4), (6, -12), (22, -8), (-6, -16))):
            swell = 1 + 0.2 * math.sin(t * 2.2 + i * 1.3 + flip)
            egg = pygame.Vector2(corner) + (x * flip, y)
            sdraw.circle(surf, (*pale, 45), egg, 9 * swell)
            sdraw.circle(surf, (*sprites.mix(spec["color"], pale, 0.6), 200), egg, 5 * swell)
            sdraw.circle(surf, (*pale, 230), egg + (-1.5, -1.5), 1.6 * swell)
    drop = pygame.Vector2(w * 0.2, 46 + 14 * math.sin(t * 1.3))  # a spiderling on its thread
    sdraw.line(surf, (*pale, 90), (drop.x, 0), drop, 1)
    blit_center(surf, silhouette("spiderling", 10), drop + (0, 6))
    body = c + (0, 14)
    blit_center(surf, silhouette(kind, 34), body)
    if t % 4.2 > 0.14:  # a blink every few seconds
        glow = 190 + 65 * math.sin(t * 1.7)
        head = body + (0, -34 * 0.78)
        for k in (-1, 1):  # the big pair, then the small ones around them
            glowing_eye(surf, head + (k * 6, -2), 2.6, glow)
            for x, y, r in ((11, 1, 1.5), (9, 6, 1.4), (3, 6, 1.3)):
                glowing_eye(surf, head + (k * x, y - 6), r, glow * 0.85)


def overlord_art(surf, w, h, spec, kind, t):
    """The Overlord: a gate, its portcullis half up, and through it a slowly turning corona of golden rays
    round his dark outline. Only his eyes and the rubies of his crown catch the light; gold dust drifts up."""
    gold = spec["color"]
    c = pygame.Vector2(w / 2, h * 0.5)
    sdraw.circle(surf, (*gold, 30), c, 62)
    for i in range(12):  # the corona, turning
        d = pygame.Vector2(1, 0).rotate(t * 8 + i * 30)
        long_ = 82 if i % 2 == 0 else 70
        sdraw.polygon(surf, (*gold, 70 if i % 2 == 0 else 45), [c + d.rotate(5) * 44, c + d * long_,
                                                                c + d.rotate(-5) * 44])
    for i in range(16):  # gold dust, rising and fading
        x = (i * 53 + 17) % w
        y = h - (t * 14 + i * 29) % h
        sdraw.circle(surf, (*gold, round(150 * y / h)), (x, y), 1.2 + (i % 3) * 0.4)
    stone, arch = (34, 31, 28), pygame.Vector2(w / 2, 58)
    for k in (-1, 1):  # the gate: two pillars and an arch, the portcullis raised halfway
        sdraw.rect(surf, stone, (arch.x + k * 104 - 11, arch.y, 22, h - arch.y))
    sdraw.polygon(surf, stone, [arch + pygame.Vector2(-1, 0).rotate(a) * r for r, rng in ((115, range(0, 181, 10)),
                  (93, range(180, -1, -10))) for a in rng])
    for x in range(-84, 85, 14):
        sdraw.line(surf, (*stone, 230), (arch.x + x, arch.y - (93 ** 2 - x ** 2) ** 0.5 + 4), (arch.x + x, 74), 2)
    sdraw.line(surf, (*stone, 230), (arch.x - 90, 74), (arch.x + 90, 74), 3)
    blit_center(surf, silhouette(kind, 30), c)
    for x in (-60, 0, 60):  # the crown's rubies (it sits round the back of his head)
        glint = pygame.Vector2(0, 1).rotate(x) * 30 * 0.515
        glowing_eye(surf, c + glint, 1.6, 150 + 100 * math.sin(t * 2 + x), sprites.RUBY)
    for k in (-1, 1):
        glowing_eye(surf, c + (k * 6, -6), 2.2, 200 + 55 * math.sin(t * 1.5), gold)


def chairman_art(surf, w, h, spec, kind, t):
    """The Chairman: a dark boardroom. A red market chart crashing across the wall behind him, coins drifting
    down, empty chairs along a long table, and his outline at its head; his tie pin and cufflinks glint gold."""
    gold, red = spec["inner"][2], (230, 50, 60)
    for x in range(20, w, 34):  # the wall's panels
        sdraw.line(surf, (*sprites.mix(spec["color"], (0, 0, 0), 0.4), 120), (x, 0), (x, h * 0.55), 1)
    chart, x = [], 14.0
    while x < w - 14:  # climbing, then the crash; drawn on from the left over and over
        k = x / w
        trend = 60 - 40 * k / 0.65 if k < 0.65 else 20 + 100 * ((k - 0.65) / 0.35) ** 1.5
        chart.append(pygame.Vector2(x, trend + 4 * math.sin(x * 0.7) + 3 * math.sin(x * 1.9)))
        x += 7
    shown = max(2, round(len(chart) * min(1.0, (t % 5) / 3)))
    for a, b in pairwise(chart[:shown]):
        sdraw.line(surf, (*red, 60), a, b, 5)
        sdraw.line(surf, (*red, 220), a, b, 2)
    tip = chart[shown - 1]
    sdraw.polygon(surf, (*red, 220), [tip + (0, 7), tip + (-5, -1), tip + (5, -1)])
    for i in range(14):  # coins drifting down, flipping
        x = (i * 61 + 23) % w
        y = (t * 22 + i * 37) % (h + 20) - 10
        cw = max(1.0, 6 * abs(math.cos(t * 3 + i)))
        sdraw.ellipse(surf, (*gold, round(200 * min(1.0, max(0.0, 1 - y / h)))), (x - cw / 2, y - 3, cw, 6))
    head = pygame.Vector2(w / 2, h * 0.5)
    table = [head + (-34, 18), head + (34, 18), head + (98, h * 0.5), head + (-98, h * 0.5)]
    sdraw.polygon(surf, (40, 26, 18), table)
    sdraw.line(surf, (90, 60, 36), table[0], table[1], 2)
    for i in range(3):  # empty chairs along either side, nearer ones bigger
        k = (i + 1) / 4
        for side in (-1, 1):
            p = table[0].lerp(table[3], k) if side < 0 else table[1].lerp(table[2], k)
            r = 5 + 6 * k
            sdraw.rect(surf, (44, 44, 56), (p.x + side * 4 - r / 2 + side * r / 2, p.y - r * 1.6, r, r * 1.6),
                       border_radius=2)
    sdraw.rect(surf, (18, 18, 24), (head.x - 30, head.y - 52, 60, 70), border_radius=8)  # his chair's high back
    blit_center(surf, silhouette(kind, 28), head)
    glint = 170 + 85 * math.sin(t * 2.4)
    glowing_eye(surf, head + (0, -6), 1.8, glint, gold)  # the tie pin
    for k in (-1, 1):
        glowing_eye(surf, head + (k * 27, 2), 1.4, 170 + 85 * math.sin(t * 2.4 + k), gold)  # cufflinks
        glowing_eye(surf, head + (k * 4, -21), 1.8, 210, gold)  # eyes under the brim


def feature_art(surf, w, h, spec, kind, t):
    """Mr Feature: a dark terminal, columns of 0s and 1s raining down it, a bug ticket stamped CLOSED pinned in
    a corner, and his outline in the middle, his big eyes glowing and his grin lit in green."""
    bits = spec["inner"][2]
    for col in range(14):  # the rain: each column falls at its own pace, its head brightest
        x = 14 + col * (w - 28) / 13
        head = (t * (40 + col * 7 % 23) + col * 37) % (h + 60)
        for i in range(7):
            y = head - i * 11
            if 0 <= y <= h:
                alpha = round(200 * (1 - i / 7))
                if (col + i + int(t * 3)) % 2:
                    sdraw.line(surf, (*bits, alpha), (x, y - 4), (x, y + 4), 1)
                else:
                    sdraw.ellipse(surf, (*bits, alpha), (x - 2.5, y - 4, 5, 8), 1)
    ticket = pygame.Rect(w - 92, 14, 76, 44)
    sdraw.rect(surf, (36, 38, 46), ticket, border_radius=3)
    for i in range(3):
        sdraw.line(surf, (90, 94, 110), (ticket.left + 8, ticket.top + 10 + i * 9), (ticket.right - 8 - i * 12,
                                                                                    ticket.top + 10 + i * 9), 2)
    sdraw.rect(surf, (200, 60, 70), ticket.inflate(-18, -24).move(4, 8), 2, border_radius=3)  # the stamp
    c = pygame.Vector2(w / 2, h / 2 + 6)
    blit_center(surf, silhouette(kind, 32), c)
    for k in (-1, 1):
        glowing_eye(surf, c + (k * 9, 2), 3.2, 210 + 45 * math.sin(t * 2), bits)
    grin = [c + (math.cos(a) * 13, 12 + math.sin(a) * 6 * (0.6 + 0.4 * math.sin(t * 5))) for a in
            (math.pi * i / 10 for i in range(11))]
    for a, b in pairwise(grin):
        sdraw.line(surf, (*bits, 220), a, b, 2)


BOSS_ART = {"brood": brood_art, "overlord": overlord_art, "chairman": chairman_art, "feature": feature_art}


class UnlockView:
    def draw_locked_shape(self, surf, kind, pos):
        """A tower the player doesn't own: its picture under a lock."""
        draw_tower_shape(surf, TOWERS[kind], pos)
        blit_center(surf, lock_image(17), pos)

    def unlock_goals(self, kind):
        """(goal, progress) for each goal of the achievement that unlocks `kind`."""
        aid = UNLOCKED_BY[kind]
        return [(goal, self.tracker.progress(goal_key(aid, i), goal)) for i, goal in enumerate(ACHIEVEMENTS[aid]["goals"])]

    @staticmethod
    def goal_text(goal, progress=None):
        """A goal as the player reads it, with how far along it is when there's more than one step."""
        if progress is None or goal["target"] <= 1:
            return goal["desc"]
        return f"{goal['desc']} ({min(int(progress), goal['target'])}/{goal['target']})"

    def needs_first(self, kind):
        """'Unlock the X (and the Y) first' while some tower `kind` is fused from is locked, else None: until
        then its achievement stays hidden."""
        missing = self.tracker.missing_prerequisites(kind)
        if not missing:
            return None
        return "Unlock " + " and ".join(f"the {TOWERS[p]['name']}" for p in missing) + " first"

    def how_to_unlock(self, kind):
        """One line saying how a locked tower is unlocked."""
        first = self.needs_first(kind)
        if first:
            return first
        text = " - or - ".join(self.goal_text(g, p) for g, p in self.unlock_goals(kind))
        if TOWERS[kind]["tier"] == 4 and self.profile.discoveries_left > 0:
            text = f"Fuse it to discover it, or: {text}"
        return text

    # ---- the card for a tower just unlocked ------------------------------------
    def draw_unlock(self):
        unlock = self.pending_unlocks[0]
        if unlock["how"] == "boss":
            return self.draw_boss_unlock(unlock)
        kind, spec = unlock["kind"], TOWERS[unlock["kind"]]
        self.shade_map(210)
        title = "DISCOVERED!" if unlock["how"] == "discovery" else "NEW TOWER UNLOCKED"
        self.text(self.font_l, title, GOLD, (MAP_W / 2, MAP_H / 2 - 190), "midtop")
        rect = pygame.Rect(MAP_W / 2 - 200, MAP_H / 2 - 140, 400, 290)
        sdraw.rect(self.screen, CARD, rect, border_radius=12)
        sdraw.rect(self.screen, spec["color"], rect, 3, border_radius=12)
        draw_tower_shape(self.screen, spec, pygame.Vector2(rect.centerx, rect.top + 48))
        self.text(self.font_l, spec["name"], spec["color"], (rect.centerx, rect.top + 82), "midtop")
        self.text(self.font_s, spec["desc"], TEXT, (rect.centerx, rect.top + 118), "midtop")
        self.text(self.font_s, self.stat_line(spec), TEXT_DIM, (rect.centerx, rect.top + 140), "midtop")
        y = rect.top + 176
        for line in self.unlock_story(unlock):
            self.text(self.font_s, line, GOLD, (rect.centerx, y), "midtop")
            y += 20
        if unlock["how"] == "discovery":
            left = self.profile.discoveries_left
            footer = f"{left} discover{'y' if left == 1 else 'ies'} left" if left else \
                "No discoveries left: the other finals need their achievements"
        else:
            footer = self.how_to_get(kind)
        self.text(self.font_s, footer, TEXT_DIM, (rect.centerx, rect.bottom - 30), "midtop")
        more = len(self.pending_unlocks) - 1
        hint = "Press any key or click to continue" + (f"  (+{more} more)" if more else "")
        self.text(self.font_s, hint, TEXT_DIM, (MAP_W / 2, rect.bottom + 20), "midtop")

    def draw_boss_unlock(self, unlock):
        """The card for a secret boss just unlocked: what earned it and only a hint of what comes next (the
        achievement's card; the boss isn't named), under art drawn after the boss (BOSS_ART)."""
        ach = BOSS_ACHIEVEMENTS[unlock["achievement"]]
        kind, card = ach["boss"], ach["card"]
        spec = ENEMY_TYPES[kind]
        glow = sprites.mix(spec["color"], spec["inner"][2], 0.5)
        self.shade_map(235)
        self.text(self.font_l, card["title"], glow, (MAP_W / 2, MAP_H / 2 - 200), "midtop")
        rect = pygame.Rect(MAP_W / 2 - 210, MAP_H / 2 - 150, 420, 310)
        sdraw.rect(self.screen, BOSS_CARD, rect, border_radius=12)
        art = pygame.Surface(sp((rect.width - 8, 170)), pygame.SRCALPHA)
        BOSS_ART.get(kind, lurker_art)(art, rect.width - 8, 170, spec, kind, pygame.time.get_ticks() / 1000)
        self.screen.blit(art, sp((rect.left + 4, rect.top + 4)))
        sdraw.rect(self.screen, spec["color"], rect, 3, border_radius=12)
        self.text(self.font, f"Achievement: {ach['name']}", GOLD, (rect.centerx, rect.top + 184), "midtop")
        self.text(self.font_s, card["deed"], TEXT, (rect.centerx, rect.top + 206), "midtop")
        for i, line in enumerate(wrap(card["lore"], 56)[:2]):
            self.text(self.font_s, line, TEXT_DIM, (rect.centerx, rect.top + 234 + i * 18), "midtop")
        self.text(self.font_s, card["hint"], glow, (rect.centerx, rect.bottom - 26), "midtop")
        if self.unlock_locked:
            return  # no hint until it can be put away
        more = len(self.pending_unlocks) - 1
        hint = "Press any key or click to continue" + (f"  (+{more} more)" if more else "")
        self.text(self.font_s, hint, TEXT_DIM, (MAP_W / 2, rect.bottom + 20), "midtop")

    @staticmethod
    def unlock_story(unlock):
        """What earned it, in a line or two."""
        kind = unlock["kind"]
        if unlock["how"] == "discovery":
            a, b = next(sorted(pair, key=list(TOWERS).index) for pair, final in CROSS.items() if final == kind)
            return [f"Found by fusing {TOWERS[a]['name']} + {TOWERS[b]['name']}"]
        ach = ACHIEVEMENTS[UNLOCKED_BY[kind]]
        return [f"Achievement: {ach['name']}"] + wrap(" - or - ".join(g["desc"] for g in ach["goals"]), 48)

    @staticmethod
    def how_to_get(kind):
        """How the player gets one on the map."""
        spec = TOWERS[kind]
        if spec["tier"] == 1:
            return "Buy it from the panel"
        if spec["tier"] == 4:
            a, b = next(sorted(pair, key=list(TOWERS).index) for pair, final in CROSS.items() if final == kind)
            return f"Fuse {TOWERS[a]['name']} + {TOWERS[b]['name']}"
        t1, t2, _ = LINES[spec["line"]]
        parent = t1 if spec["tier"] == 2 else t2
        return f"Fuse two {TOWERS[parent]['name']}s" + (" and pick this branch" if spec["tier"] == 3 else "")

    # ---- the next unlock, pinned in the panel ----------------------------------------
    def draw_next_goal(self, x, y):
        """The locked tower closest to unlocking, its goal and a progress bar. Returns False if every
        tower is owned (nothing drawn)."""
        closest = self.tracker.closest()
        if not closest:
            return False
        kind, goal, progress = closest
        w = PANEL_W - 24
        self.text(self.font_s, "NEXT UNLOCK", TEXT_DIM, (x, y))
        self.text(self.font_s, TOWERS[kind]["name"], TOWERS[kind]["color"], (x + w, y), "topright")
        for i, line in enumerate(wrap(goal["desc"], 28)[:2]):
            self.text(self.font_s, line, TEXT, (x, y + 18 + i * 16))
        bar = pygame.Rect(x, y + 56, w, 6)
        sdraw.rect(self.screen, PANEL_LINE, bar, border_radius=3)
        share = min(progress / goal["target"], 1)
        if share > 0:
            sdraw.rect(self.screen, GOLD, (bar.x, bar.y, max(bar.width * share, 6), bar.height), border_radius=3)
        if goal["target"] > 1:
            self.text(self.font_s, f"{int(progress)}/{goal['target']}", TEXT_DIM, (x + w, y + 66), "topright")
        return True

