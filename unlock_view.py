"""Drawing for tower unlocks (achievements.py): the card for a tower just unlocked, the next unlock
pinned in the panel, and the lock drawn over towers the player doesn't own yet. Mixed into
graphics.GameView, which uses these in the build panel, the branch choice and the evolution tree.
"""

import pygame

from achievements import ACHIEVEMENTS, UNLOCKED_BY, goal_key
from graphics import (CARD, GOLD, MAP_H, MAP_W, PANEL_LINE, PANEL_W, TEXT, TEXT_DIM, blit_center, draw_tower_shape,
                      sdraw, sp, wrap)
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

