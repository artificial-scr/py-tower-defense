"""analytics/matchups.py: its comps, its headless waves and the analysis of the matrix."""

import math
import os
import sys

import pytest

from levels import wave_hp_mult

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "analytics"))
import matchups

MID_HP = wave_hp_mult(4, 2)


def test_comps_spend_about_the_gold():
    assert matchups.solo("railgun", 2400) == [("railgun", 4)]
    assert matchups.solo("gun", 10_000) == [("gun", matchups.MAX_TOWERS)]
    comp = matchups.mixed("blizzard", "bombard", 2400, 0.5)
    assert comp == [("blizzard", 4), ("bombard", 4)]
    assert matchups.comp_label(comp) == "blizzard+bombard 44%"


def test_frost_line_supports_only_mix_with_their_tier():
    for name in matchups.CHECKPOINTS:
        solos, mixes = matchups.comps_for(name)
        assert not any(kind in matchups.SUPPORT_ONLY for comp in solos for kind, _ in comp)
        for (support, partner, _), comp in mixes.items():
            assert partner not in matchups.SUPPORT_ONLY
            assert matchups.TOWERS[support]["tier"] == matchups.TOWERS[partner]["tier"]
            assert [k for k, _ in comp] == [support, partner]
    solos, _ = matchups.comps_for("mid")
    assert [("shatter", 9)] in solos  # Shatter is a comp of its own


def test_towers_go_on_free_tiles_best_first():
    placement = matchups.place([("gun", 3), ("railgun", 1)])
    tiles = [tile for _, tile in placement]
    assert len(set(tiles)) == 4 and not set(tiles) & matchups.PATH_CELLS
    assert placement[0][0] == "railgun"


def test_supports_spread_out_and_damage_gathers_on_them():
    placement = matchups.place([("frost", 2), ("gun", 4)])
    assert [k for k, _ in placement] == ["frost", "frost", "gun", "gun", "gun", "gun"]
    cells = [matchups.tile_center(*c) for c in matchups.PATH_CELLS]

    def reach(kind, tile):
        return {i for i, p in enumerate(cells)
                if p.distance_to(matchups.tile_center(*tile)) <= matchups.TOWERS[kind]["range"]}

    (_, a), (_, b) = placement[:2]
    assert not reach("frost", a) & reach("frost", b)
    slowed = reach("frost", a) | reach("frost", b)
    assert all(reach("gun", t) & slowed for _, t in placement[2:])
    assert sum(len(reach("gun", t) & slowed) for _, t in placement[2:]) >= \
        sum(len(reach("gun", t) & slowed) for t in [t for _, t in matchups.place([("gun", 4)])])


def test_a_gun_stops_one_basic_but_not_a_crowd_of_elites():
    gun = matchups.place([("gun", 1)])
    assert not matchups.leaks(gun, "basic", 1, 1.0)
    assert matchups.leaks(gun, "champion", 20, MID_HP)


def test_cells_are_cheaper_against_easier_monsters():
    gold, capped = matchups.cell([("railgun", 2)], "basic", MID_HP)
    assert not capped and gold < matchups.cell([("railgun", 2)], "champion", MID_HP)[0]


@pytest.mark.slow
def test_slows_dont_help_against_juggernauts():
    """Juggernauts are immune to slows: a Blizzard's gold saves the Bombards less against them than against Tanks."""
    comp = matchups.mixed("blizzard", "bombard", 2400, 0.5)
    alone = matchups.solo("bombard", 2400)
    saved = {m: 1 - matchups.cell(comp, m, MID_HP)[0] / matchups.cell(alone, m, MID_HP)[0]
             for m in ("tank", "juggernaut")}
    assert saved["juggernaut"] < 0 < saved["tank"]  # 50%: a 25% mix saves next to nothing against Tanks either


def test_equilibrium_of_rock_paper_scissors_is_even():
    beats = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
    table = {t: {m: 50 if beats[t] == m else 200 if beats[m] == t else 100 for m in beats} for t in beats}
    pt, pm, _ = matchups.equilibrium(table, list(beats))
    assert all(w == pytest.approx(1 / 3, abs=0.03) for w in [*pt.values(), *pm.values()])


def test_a_dominant_comp_takes_the_equilibrium_and_shows_as_dominating():
    table = {"strong": {"a": 50, "b": 60}, "weak": {"a": 100, "b": math.inf}}
    pt, pm, _ = matchups.equilibrium(table, ["a", "b"])
    assert pt["strong"] > 0.95 and pm["b"] > 0.95
    assert matchups.dominated(table, ["a", "b"]) == ["comp weak is beaten everywhere by strong",
                                                    "monster a is beaten everywhere by b"]


def test_fair_costs_even_out_the_gold_stopped():
    table = {"t": {"basic": 50, "tank": 200}}
    rows = {r["monster"]: r for r in matchups.fair_costs(table, ["basic", "tank"])}
    assert rows["basic"]["fair cost"] == pytest.approx(rows["basic"]["cost"] * 0.5)
    assert rows["tank"]["fair cost"] == pytest.approx(rows["tank"]["cost"] * 2)
