"""Progress that outlives a level: tower compositions, and the permanent profile.

The profile (profile.json) is kept forever, across runs: the records each side plays against,
unlocks, and milestones. See DESIGN.md for how the pieces fit together.

Records are kept per level and per wave, and a slot is only replaced by something stronger
(higher value; a tie keeps the old one), so the challenge never gets easier.
"""

import json
import os
from collections import defaultdict

from monsters import ABILITIES, ENEMY_TYPES
from towers import LINES, NO_TOWER_MODS, read_json

PROFILE_VERSION = 1
UNLOCKS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "unlocks.json")
ABILITY_RANK_COOLDOWN = 0.85  # each extra rank of an ability multiplies its cooldown by this

# --------------------------------------------------------------------------
# Unlock cards (unlocks.json)
# --------------------------------------------------------------------------
# side -> effect -> the fields it needs
CARD_EFFECTS = {
    "monster": {"type": ("type",), "ability": ("ability",), "buff": ("mod", "per_rank"), "budget": ("per_rank",)},
    "tower": {"damage": ("line", "per_rank"), "range": ("per_rank",), "gold": ("per_rank",), "lives": ("per_rank",),
              "refund": ("per_rank",), "detector": (), "armor": ("per_rank",), "grounding": ("per_rank",)},
}
CARD_FIELDS = ("name", "desc", "effect", "weight")
CARD_EXTRAS = ("max", "rare", "type", "ability", "mod", "per_rank", "line")
BUFF_MODS = ("hp", "speed", "burn", "thaw")


def load_unlocks(path):
    """Return {side: {card id: card}} from unlocks.json, with max and rare filled in."""
    data = read_json(path)
    name = os.path.basename(path)
    pools = {}
    for side, effects in CARD_EFFECTS.items():
        pools[side] = {}
        for key, raw in data[side].items():
            def fail(message):
                raise ValueError(f"{name}: {side} card {key!r}: {message}")
            missing = [f for f in CARD_FIELDS if f not in raw]
            unknown = [f for f in raw if f not in CARD_FIELDS + CARD_EXTRAS]
            if missing or unknown:
                fail(f"missing fields {missing}" if missing else f"unknown fields {unknown}")
            if raw["effect"] not in effects:
                fail(f"effect must be one of {tuple(effects)}")
            needs = [f for f in effects[raw["effect"]] if f not in raw]
            if needs:
                fail(f"{raw['effect']} needs {needs}")
            if raw.get("type") and ENEMY_TYPES.get(raw["type"], {}).get("draft") != "unlock":
                fail(f"{raw['type']!r} isn't an enemy with draft: unlock")
            if raw.get("ability") and raw["ability"] not in ABILITIES:
                fail(f"{raw['ability']!r} isn't an ability")
            if raw.get("mod") and raw["mod"] not in BUFF_MODS:
                fail(f"mod must be one of {BUFF_MODS}")
            if raw.get("line") and raw["line"] not in LINES:
                fail(f"{raw['line']!r} isn't a tower line")
            pools[side][key] = {"max": 1, "rare": False, **raw}
    return pools


UNLOCKS = load_unlocks(UNLOCKS_FILE)


def comp_snapshot(towers, t, trigger, wave, during_wave):
    """The towers on the map as a composition: value (gold put into them), what's in it, when."""
    towers = sorted(towers, key=lambda tw: (-tw.spent, tw.uid))
    by_kind = defaultdict(int)
    for tw in towers:
        by_kind[tw.kind] += 1
    return {
        "value": sum(tw.spent for tw in towers), "t": round(t, 2), "trigger": trigger, "wave": wave,
        "during_wave": during_wave, "tower_count": len(towers), "by_kind": dict(by_kind),
        "towers": [{"id": tw.uid, "kind": tw.kind, "tier": tw.tier, "gold_spent": tw.spent, "tile": list(tw.tile)}
                   for tw in towers],
    }


def stronger(new, old):
    """Whether a comp or wave `new` should replace `old` (None counts as nothing)."""
    return new is not None and new["value"] > 0 and (old is None or new["value"] > old["value"])


class Profile:
    """Permanent progress. Every change is written straight to disk."""

    def __init__(self, path, data=None):
        self.path = path
        data = data or {}
        self.tower_records = data.get("tower_records", {})  # "level" -> "wave" -> {"value", "towers", ...}
        self.monster_records = data.get("monster_records", {})  # "level" -> "wave" -> {"value", "queue", ...}
        # side -> card id -> rank; cards no longer in unlocks.json are dropped
        saved = data.get("unlocks", {})
        self.unlocks = {side: {k: min(int(r), UNLOCKS[side][k]["max"]) for k, r in saved.get(side, {}).items()
                               if k in UNLOCKS[side]}
                        for side in UNLOCKS}
        # monsters_side: Towers' last level beaten once (the Monsters side opens);
        # tower_cards: Monsters' last level beaten once (Towers-side wins give tower cards);
        # starter_pack: the first time on the Monsters side, its starter cards were picked
        self.milestones = {"monsters_side": False, "tower_cards": False, "starter_pack": False,
                           **data.get("milestones", {})}
        self.best_run = data.get("best_run", 0)  # most levels won in one run

    @classmethod
    def load(cls, path):
        """The profile at `path`, or a fresh one if it's missing or unreadable."""
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or data.get("version") != PROFILE_VERSION:
                raise ValueError("not a profile")
            return cls(path, data)
        except (OSError, ValueError, TypeError) as err:
            if not isinstance(err, FileNotFoundError):
                print(f"Ignoring unreadable profile {path}: {err}")
            return cls(path)

    def to_dict(self):
        return {"version": PROFILE_VERSION, "milestones": self.milestones, "best_run": self.best_run,
                "unlocks": self.unlocks, "tower_records": self.tower_records, "monster_records": self.monster_records}

    def reach(self, milestone):
        if not self.milestones[milestone]:
            self.milestones[milestone] = True
            self.save()

    def note_run(self, levels_won):
        if levels_won > self.best_run:
            self.best_run = levels_won
            self.save()

    def reward_side(self, side_won):
        """The card pool a win on `side_won` draws from, or None if that side gives no cards yet."""
        if side_won == "towers" and not self.milestones["tower_cards"]:
            return None
        return "monster" if side_won == "monsters" else "tower"

    def draw_cards(self, pool, rng, n=3, rare=False):
        """Up to n different card ids from a pool, weighted, leaving out cards already at max rank. With
        `rare`, the first is a rare card (if any are left)."""
        open_cards = {k: c for k, c in UNLOCKS[pool].items() if self.rank(pool, k) < c["max"]}
        cards = []
        rares = [k for k, c in open_cards.items() if c["rare"]]
        if rare and rares and n:
            pick = rng.choices(rares, weights=[open_cards[k]["weight"] for k in rares])[0]
            cards.append(pick)
            del open_cards[pick]
        while open_cards and len(cards) < n:
            pick = rng.choices(list(open_cards), weights=[c["weight"] for c in open_cards.values()])[0]
            cards.append(pick)
            del open_cards[pick]
        return cards

    # ---- unlocks ----------------------------------------------------------------
    def rank(self, side, card):
        return self.unlocks[side].get(card, 0)

    def unlock(self, side, card):
        """Add a rank to a card (up to its max)."""
        self.unlocks[side][card] = min(self.rank(side, card) + 1, UNLOCKS[side][card]["max"])
        self.save()

    def owned(self, side, effect):
        """(card, rank) for the cards of an effect the player has."""
        return [(UNLOCKS[side][k], r) for k, r in self.unlocks[side].items() if UNLOCKS[side][k]["effect"] == effect]

    def draftable(self):
        """Monster kinds the monster player can draft (bosses are added on boss levels' last waves)."""
        unlocked = {card["type"] for card, _ in self.owned("monster", "type")}
        return [k for k, s in ENEMY_TYPES.items() if s["draft"] == "starter" or k in unlocked]

    def abilities(self):
        """Unlocked ability ids, in monsters.json order, with their cooldown after rank bonuses."""
        ranks = {card["ability"]: r for card, r in self.owned("monster", "ability")}
        return {k: ABILITIES[k]["cooldown"] * ABILITY_RANK_COOLDOWN ** (ranks[k] - 1) for k in ABILITIES if k in ranks}

    def monster_mods(self):
        """Enemy modifiers from monster buffs (see entities.Enemy)."""
        mods = {"hp": 1.0, "speed": 1.0, "burn": 1.0, "thaw": 0.0}
        for card, r in self.owned("monster", "buff"):
            mods[card["mod"]] += card["per_rank"] * r
        return mods

    def budget_mult(self):
        return 1 + sum(card["per_rank"] * r for card, r in self.owned("monster", "budget"))

    def tower_mods(self):
        """What the player's tower cards change (see towers.NO_TOWER_MODS)."""
        mods = {**NO_TOWER_MODS, "damage": dict(NO_TOWER_MODS["damage"])}
        for key, r in self.unlocks["tower"].items():
            card = UNLOCKS["tower"][key]
            effect = card["effect"]
            if effect == "damage":
                mods["damage"][card["line"]] += card["per_rank"] * r
            elif effect == "detector":
                mods["detector"] = True
            else:
                mods[effect] += card["per_rank"] * r
        return mods

    def save(self):
        if not self.path:
            return
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=1)
            os.replace(tmp, self.path)
        except OSError as err:
            print(f"Could not save the profile: {err}")

    # ---- records --------------------------------------------------------------
    def tower_record(self, level):
        """{wave number: {"value", "mods", "towers": [{"kind", "tile", "gold_spent"}]}} for a level (1-based)."""
        return {int(w): slot for w, slot in self.tower_records.get(str(level), {}).items()}

    def record_towers(self, level, comps_by_wave, mods=None):
        """Store a cleared level's per-wave comps, slot by slot where they beat the stored one, with
        the tower card modifiers they had (towers.NO_TOWER_MODS). Returns the wave numbers that changed."""
        slots = self.tower_records.setdefault(str(level), {})
        changed = []
        for wave, comp in sorted(comps_by_wave.items()):
            if stronger(comp, slots.get(str(wave))):
                slots[str(wave)] = {"value": comp["value"], "mods": mods or NO_TOWER_MODS,
                                    "towers": [{"kind": tw["kind"], "tile": tw["tile"], "gold_spent": tw["gold_spent"]}
                                               for tw in comp["towers"]]}
                changed.append(wave)
        if changed:
            self.save()
        return changed

    def monster_record(self, level):
        """{wave number: {"value", "queue", "hp_mult", "mods", "casts"}} for a level (1-based)."""
        return {int(w): slot for w, slot in self.monster_records.get(str(level), {}).items()}

    def record_monsters(self, level, waves):
        """Store a won level's waves ({wave number: wave}), slot by slot where they beat the stored
        one. Returns the wave numbers that changed."""
        slots = self.monster_records.setdefault(str(level), {})
        changed = [w for w, wave in sorted(waves.items()) if stronger(wave, slots.get(str(w)))]
        for w in changed:
            slots[str(w)] = waves[w]
        if changed:
            self.save()
        return changed
