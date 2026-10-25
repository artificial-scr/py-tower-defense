"""Tooltips: right click a tower or a monster on the map, a tower's build button, a monster in the wave preview or
the Monsters side's draft list, or a tower on the evolution tree, for a small card with its stats and a line about
it. Mixed into main.Game (after graphics.GameView, whose layout it reads).

Stats are the ones that count right now: tower cards, the wave's hp multiplier and the monster player's upgrades
included, each changed value followed by its base value in grey. A tooltip on a monster or tower on the map
follows it, live, and goes when it does. A left click, a key or a right click on nothing closes one (Esc closes
the evolution tree with it). Tooltips don't pause the game, and opening or closing one leaves a pause alone.
"""

from dataclasses import dataclass

import pygame

import graphics
from entities import NO_MODS
from graphics import (
    BAD,
    CARD,
    GOLD,
    GOOD,
    MAP_H,
    MAP_W,
    TEXT,
    TEXT_DIM,
    TIER_RIM,
    boss_color,
    sdraw,
)
from levels import TILE, wave_hp_mult
from monsters import ENEMY_TYPES, summon_kinds
from towers import CROSS, EVOLVE, TARGET_DESC, TARGETING, TOWERS, card_damage

TIP_W = 250  # a tooltip's width, in logical units
TIP_PAD = 8
TIP_GAP = 14  # between the point clicked (or the thing followed) and the card
LINE_H = 15


@dataclass
class Tip:
    """What a tooltip shows: a tower or monster kind ("tower" / "monster"), the Tower or Enemy on the map if it's one
    (followed, live), where it was opened, and for a wave preview icon, how many of the kind are coming."""
    what: str
    kind: str
    obj: object = None
    anchor: pygame.Vector2 = None
    count: int = None
    where: str = "map"  # map, panel or tree


def plural(name, n):
    return name if n == 1 else name + "s"


def monster_traits(spec, side):
    """One line for each mechanic a monster has, numbers included. Secret bosses' ambushes stay secret."""
    lines = []
    if "heal_aura" in spec:
        r, share = spec["heal_aura"]
        lines.append(f"Heals monsters within {r} by {share:.0%} max HP/s")
    if "split" in spec:
        kind, n = spec["split"]
        lines.append(f"Splits into {n} {plural(ENEMY_TYPES[kind]['name'], n)} when killed")
    if "phase" in spec:
        every, duration = spec["phase"]
        lines.append(f"Out of reach {duration:g} s of every {every:g} s")
    if spec.get("slow_floor", 0) >= 1:
        lines.append("Immune to slows")
    elif "slow_floor" in spec:
        lines.append(f"Slows can't take it under {spec['slow_floor']:.0%} speed")
    if "summon" in spec:
        kinds, n, every = spec["summon"][:3]
        names = " and ".join(plural(ENEMY_TYPES[k]["name"], 2) for k in dict.fromkeys(summon_kinds(kinds)))
        more = f" (up to {spec['summon_max']})" if "summon_max" in spec else ""
        lines.append(f"Calls {n}{more} {names} every {every:g} s")
    if "ward" in spec:
        lines.append(f"Its ward absorbs a whole hit, back after {spec['ward']:g} s")
    if "decoy" in spec:
        every, ahead, _ = spec["decoy"]
        lines.append(f"Sends an illusion {ahead:g} ahead every {every:g} s")
    if "enrage" in spec:
        lines.append(f"Up to {spec['enrage']:+.0%} speed as it loses HP")
    if "rebound" in spec:
        share, duration = spec["rebound"]
        lines.append(f"{share:+.0%} speed for {duration:g} s when a slow wears off")
    if "sabotage" in spec:
        r, duration = spec["sabotage"]
        lines.append(f"When killed, towers within {r} stop for {duration:g} s")
    if "loot" in spec:
        share, budget = spec["loot"]
        lines.append(f"Steals {share:.0%} of the gold if it gets through" if side == "towers"
                     else f"Brings back {budget:g}x its cost if it gets through")
    if "speed_aura" in spec:
        r, share = spec["speed_aura"]
        lines.append(f"Monsters within {r} move {share:+.0%} faster")
    if "layoff" in spec:
        every, r, duration = spec["layoff"]
        lines.append(f"Every {every:g} s the costliest tower within {r} stops for {duration:g} s")
    if "zap" in spec:
        every, r, count = spec["zap"]
        lines.append(f"Every {every:g} s zaps the {count} nearest towers within {r} to random spots")
    if "dividends" in spec:
        lines.append("Looters that get through give it a barrier")
    if "severance" in spec and side == "towers":
        lines.append("When killed, gives back the gold Looters stole")
    if spec.get("bankrupts"):
        lines.append("If it gets through: every coin and every tower")
    return lines


def monster_status(e):
    """What's happening to a monster on the map right now."""
    lines = []
    if e.illusion:
        lines.append(("An illusion: one hit pops it", GOLD))
    if e.phased:
        lines.append(("Out of reach", TEXT))
    if e.slowed and e.slow_factor < 1:
        lines.append((f"Slowed to {e.slow_factor:.0%} speed ({e.slow_timer:.1f} s)", TEXT))
    elif e.rebounding:
        lines.append((f"Sprinting ({e.rebound_timer:.1f} s)", BAD))
    if e.burning:
        lines.append((f"Burning {e.burn_dps:.0f}/s ({e.burn_timer:.1f} s)", TEXT))
    if "ward" in e.spec:
        lines.append(("Ward up", TEXT) if e.warded else (f"Ward back in {e.ward_timer:.1f} s", TEXT_DIM))
    if e.barrier > 0:
        lines.append((f"Barrier {e.barrier:.0f}", TEXT))
    if e.shield_timer > 0:
        lines.append((f"Shielded: {e.shield:.0%} less damage", TEXT))
    if e.haste_timer > 0:
        lines.append((f"Hasted {e.haste:+.0%}", TEXT))
    return lines


def stat(label, value, base=None, fmt="{:.0f}"):
    """A stat line's segments: the value, and the base value in grey when cards or buffs changed it."""
    segments = [(f"{label} {fmt.format(value)}", TEXT)]
    if base is not None and fmt.format(base) != fmt.format(value):
        segments.append((f"  ({fmt.format(base)})", TEXT_DIM))
    return segments


class TooltipView:
    # ---- what's under a right click ----------------------------------------------------
    def tooltip_at(self, pos):
        """The Tip for what's at `pos` (logical), or None."""
        pos = pygame.Vector2(pos)
        if self.show_tree:
            for kind, x, y, w in self.tree_spots():
                if pygame.Rect(x, y - 18, w, 36).collidepoint(pos):
                    return Tip("tower", kind, anchor=pos, where="tree")
            return None
        if pos.x < MAP_W:
            if self.side == "monsters" and any(c.distance_to(pos) <= 10 for _, c in self.queue_icons()):
                return None  # the queue's icons: a click takes a monster off
            near = [(e.pos.distance_to(pos), e) for e in self.enemies if e.alive]
            near = [(d, e) for d, e in near if d <= e.spec["size"] + 4]
            if near:
                e = min(near, key=lambda de: de[0])[1]
                return Tip("monster", e.kind, e)
            tower = self.towers.get((int(pos.x) // TILE, int(pos.y) // TILE))
            return Tip("tower", tower.kind, tower) if tower else None
        if self.side == "towers":
            for kind, b in self.tower_buttons.items():
                if b.rect.collidepoint(pos):
                    return Tip("tower", kind, anchor=pos, where="panel")
            for kind, n, center in self.preview_icons():
                if center.distance_to(pos) <= 12:
                    return Tip("monster", kind, anchor=pos, count=n, where="panel")
        elif self.state == "build":
            for kind, rect in self.attack_rows():
                if rect.collidepoint(pos):
                    return Tip("monster", kind, anchor=pos, where="panel")
        return None

    @property
    def active_tooltip(self):
        """The tooltip, unless what it follows has died, been sold or been fused away."""
        tip = self.tooltip
        if tip is None or tip.obj is None:
            return tip
        alive = tip.obj.alive and tip.obj in self.enemies if tip.what == "monster" else (
            self.towers.get(tip.obj.tile) is tip.obj)
        return tip if alive else None

    # ---- what it says --------------------------------------------------------------
    def monster_outlook(self):
        """(hp multiplier, monster mods) monsters sent now would have: the coming wave's in the build phase."""
        if self.state != "build":
            return self.hp_mult, self.wave_mods
        if self.side == "monsters":
            return (wave_hp_mult(self.level_idx, self.wave_idx),
                    {**self.upgrade_mods(), "armor": self.defender_mods["armor"]})
        recorded, wave = self.next_wave()
        mods = dict(recorded["mods"]) if recorded else {}
        mods["armor"] = self.card_mods["armor"]
        return wave.hp_mult, mods

    def tower_tip(self, tip):
        """(title, title color, tag, tag color, desc, lines) for a tower tooltip."""
        kind, t = tip.kind, tip.obj
        spec = TOWERS[kind]
        owned = self.profile.has_tower(kind) or t is not None
        if spec["tier"] == 4 and not owned and self.profile.discoveries_left > 0:
            a, b = next(pair for pair, k in CROSS.items() if k == kind)
            return ("???", TEXT_DIM, "Tier 4", TIER_RIM[4], "A final form not yet found",
                    [[(f"Fuse {TOWERS[a]['name']} + {TOWERS[b]['name']} to discover it", GOLD)]])
        mods = t.mods if t else self.card_mods
        lines = []
        damage, burn = card_damage(kind, mods), spec.get("burn", 0) * mods["burn"]
        if spec["damage"]:
            hit = stat("Damage", damage, spec["damage"])
            if "multishot" in spec:
                hit.append((f"  x{spec['multishot']} targets", TEXT))
            lines.append(hit)
        dps = f"  DPS {damage * spec['rate']:.0f}" if spec["damage"] else ""
        lines.append([(f"Rate {spec['rate']:g}/s{dps}", TEXT)])
        lines.append(stat("Range", t.range if t else spec["range"] * mods["range"], spec["range"]))
        if t:
            lines.append([(f"Target: {TARGETING[t.targeting]} ({TARGET_DESC[t.targeting]})", TEXT)])
        if "splash" in spec:
            lines.append(stat("Splash", spec["splash"]))
        if "chain" in spec:
            lines.append([(f"Chains to {spec['chain']} more enemies", TEXT)])
        if "instant" in spec:
            lines.append([("Beam: hits at once", TEXT)])
        if "slow" in spec:
            lines.append([(f"Slows to {spec['slow']:.0%} speed for {spec['slow_time']:g} s", TEXT)])
        if burn:
            lines.append([(f"Burn {burn:.0f}/s for {spec['burn_time']:g} s", TEXT)]
                         + stat("", burn, spec["burn"])[1:])
        for key, against in (("vs_slowed", "slowed"), ("vs_burning", "burning")):
            if key in spec:
                lines.append([(f"x{spec[key]:g} damage vs {against} enemies", GOOD)])
        if t and self.side == "towers":
            total = sum(other.wave_damage for other in self.towers.values())
            share = f" ({t.wave_damage / total:.0%})" if total else ""  # of all the towers' damage
            lines.append([(f"Dealt {t.wave_damage:.0f} damage this wave{share}", TEXT_DIM)])
        if self.side == "towers" or tip.where == "tree":
            lines.append([(self.tower_path(kind), GOLD)])
            if not owned:
                lines.append([("Locked: " + self.how_to_unlock(kind), BAD)])
        if t and self.side == "towers":
            tag = f"Tier {spec['tier']}  Sell {t.sell_value}g"
        elif spec["cost"]:
            tag = f"Tier {spec['tier']}  {spec['cost']}g"
        else:
            tag = f"Tier {spec['tier']}"
        return spec["name"], spec["color"], tag, TIER_RIM[spec["tier"]] if spec["tier"] > 1 else TEXT_DIM, \
            spec["desc"], lines

    def tower_path(self, kind):
        """Where a tower goes next: what two of it fuse into, or the finals it makes with another line."""
        tier = TOWERS[kind]["tier"]
        if tier == 4:
            return "Final form"
        if tier < 3:
            return "Two fuse into " + " or ".join(TOWERS[k]["name"] for k in EVOLVE[kind])
        hide = self.profile.discoveries_left > 0
        finals = [(next(p for p in pair if p != kind), final) for pair, final in CROSS.items() if kind in pair]
        names = [f"{'???' if hide and not self.profile.has_tower(f) else TOWERS[f]['name']} (+{TOWERS[p]['name']})"
                 for p, f in finals]
        return "Finals: " + ", ".join(names)

    def monster_tip(self, tip):
        """(title, title color, tag, tag color, desc, lines) for a monster tooltip."""
        kind, e = tip.kind, tip.obj
        spec = ENEMY_TYPES[kind]
        if e:
            hp_mult, mods = e.hp_mult, e.mods
        else:
            hp_mult, mods = self.monster_outlook()
            mods = {**NO_MODS, **mods}
        max_hp = spec["hp"] * hp_mult * mods["hp"]
        armor = (spec.get("armor", 0) + mods["armor_flat"]) * mods["armor"]
        lines = []
        if e:
            lines.append([(f"HP {e.hp:.0f} / {e.max_hp:.0f}", TEXT)] + stat("", e.max_hp, spec["hp"])[1:])
        else:
            lines.append(stat("HP", max_hp, spec["hp"]))
        if armor or spec.get("armor"):
            lines.append(stat("Armor", armor, spec.get("armor", 0), "{:g}"))
        lines.append(stat("Speed", e.speed if e else spec["speed"] * mods["speed"], spec["speed"]))
        bounty = f"Bounty {spec['cost']}g" if self.side == "towers" else f"Cost {spec['cost']}"
        if spec.get("fatal"):
            lives = "takes every life"
        elif spec["damage"]:
            lives = f"takes {spec['damage']} {'life' if spec['damage'] == 1 else 'lives'}"
        else:
            lives = "takes no lives"
        lines.append([(f"{bounty}, {lives}", GOLD)])
        lines += [[(trait, TEXT)] for trait in monster_traits(spec, self.side)]
        if e:
            lines += [[seg] for seg in monster_status(e)]
        if tip.count:
            lines.append([(f"{tip.count} in this wave" if self.state == "build" else f"{tip.count} still to come",
                           TEXT_DIM)])
        if "boss" in spec:
            tag, color = "Boss", boss_color(spec)
        elif spec.get("elite"):
            tag, color = "Elite", GOLD
        else:
            tag, color = "", TEXT_DIM
        title_color = boss_color(spec) if "boss" in spec else spec["color"]
        return spec["name"], title_color, tag, color, spec.get("desc", ""), lines

    def wrap_tip(self, text, font=None):
        """`text` split into lines that fit a tooltip."""
        font = font or self.font_s
        width = (TIP_W - 2 * TIP_PAD) * graphics.SCALE
        lines, line = [], ""
        for word in text.split():
            if line and font.size(f"{line} {word}")[0] > width:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        return lines + [line] if line else lines

    # ---- drawing --------------------------------------------------------------------
    def draw_tooltip(self):
        """The card, beside what it's about, always on the map (so it never covers the panel)."""
        tip = self.active_tooltip
        if tip is None:
            return
        title, title_color, tag, tag_color, desc, lines = (self.tower_tip if tip.what == "tower"
                                                            else self.monster_tip)(tip)
        desc_lines = self.wrap_tip(desc)
        # a line of one piece wraps; a stat line with its base value in grey is short enough as it is
        lines = [wrapped for segs in lines for wrapped in
                 ([[(part, segs[0][1])] for part in self.wrap_tip(segs[0][0])] if len(segs) == 1 else [segs])]
        height = TIP_PAD * 2 + 20 + LINE_H * len(desc_lines) + 6 + LINE_H * len(lines)
        anchor = tip.obj.pos if tip.obj is not None else tip.anchor
        x = anchor.x + TIP_GAP
        if x + TIP_W > MAP_W - 4:
            x = anchor.x - TIP_GAP - TIP_W
        x = max(4, min(x, MAP_W - 4 - TIP_W))
        y = max(4, min(anchor.y - 10, MAP_H - 4 - height))
        rect = pygame.Rect(x, y, TIP_W, height)
        sdraw.rect(self.screen, CARD, rect, border_radius=8)
        sdraw.rect(self.screen, title_color, rect, 2, border_radius=8)
        left, top = x + TIP_PAD, y + TIP_PAD
        font = self.fit_font(title, TIP_W - 2 * TIP_PAD - 90, self.font, self.font_s)
        self.text(font, title, title_color, (left, top + 7), "midleft")
        if tag:
            self.text(self.font_s, tag, tag_color, (rect.right - TIP_PAD, top + 7), "midright")
        top += 20
        for line in desc_lines:
            self.text(self.font_s, line, TEXT_DIM, (left, top + LINE_H / 2), "midleft")
            top += LINE_H
        top += 6
        for segments in lines:
            cx = left
            for text, color in segments:
                if not text:
                    continue
                r = self.text(self.font_s, text, color, (cx, top + LINE_H / 2), "midleft")
                cx = r.right / graphics.SCALE
            top += LINE_H
