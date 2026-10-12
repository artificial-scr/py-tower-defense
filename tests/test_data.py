"""towers.json / evolution.json loading and validation, and the level data."""

import itertools
import json

import pytest

import towers
from levels import (ALL_BOSS_LEVELS, ALL_LEVELS, BOSS_LEVELS, COLS, LEVEL_COUNT, LEVELS, ROWS, THEMES,
                    build_path_cells, make_wave)
from towers import CROSS, EVOLVE, LINES, TOWER_ORDER, TOWERS, fusion_options, load_evolution, load_towers


# ---- the shipped data ----------------------------------------------------
def test_tree_shape():
    assert TOWER_ORDER == ["gun", "cannon", "frost"]
    assert len(TOWERS) == 24
    assert [sum(s["tier"] == t for s in TOWERS.values()) for t in (1, 2, 3, 4)] == [3, 3, 6, 12]
    for line, (t1, t2, branches) in LINES.items():
        assert EVOLVE[t1] == [t2] and EVOLVE[t2] == list(branches)
        assert all(TOWERS[k]["line"] == line for k in (t1, t2, *branches))


def test_every_cross_pair_has_its_own_final():
    tier3 = [k for k, s in TOWERS.items() if s["tier"] == 3]
    pairs = [p for p in itertools.combinations(tier3, 2) if TOWERS[p[0]]["line"] != TOWERS[p[1]]["line"]]
    assert len(pairs) == 12
    finals = [fusion_options(*p) for p in pairs]
    assert all(len(f) == 1 and TOWERS[f[0]]["tier"] == 4 for f in finals)
    assert len({f[0] for f in finals}) == 12 == len(set(CROSS.values()))


def test_fusion_rules():
    assert fusion_options("gun", "gun") == ["rifle"]
    assert fusion_options("rifle", "rifle") == ["minigun", "sniper"]
    assert fusion_options("sniper", "bombard") == fusion_options("bombard", "sniper") == ["railgun"]
    assert fusion_options("sniper", "sniper") == []      # identical tier 3 don't fuse
    assert fusion_options("minigun", "sniper") == []     # same line
    assert fusion_options("gun", "cannon") == []
    assert fusion_options("railgun", "railgun") == []    # finals are final


def test_tower_fields():
    for kind, s in TOWERS.items():
        assert s["range"] > 0 and s["damage"] > 0 and s["rate"] > 0, kind
        assert (s["cost"] is not None) == (s["tier"] == 1), kind
        assert all(len(c) == 3 for _, _, c in s["look"]["layers"]), kind


# ---- validation: broken files fail at startup with a clear message ----------
def real(name):
    with open(towers.TOWERS_FILE if name == "towers" else towers.EVOLUTION_FILE, encoding="utf-8") as f:
        return json.load(f)


def write(tmp_path, name, data):
    path = tmp_path / f"{name}.json"
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return str(path)


def tower_error(tmp_path, change):
    data = real("towers")
    change(data["towers"])
    with pytest.raises(ValueError) as err:
        load_towers(write(tmp_path, "towers", data))
    return str(err.value)


def evolution_error(tmp_path, change):
    data = real("evolution")
    change(data)
    with pytest.raises(ValueError) as err:
        load_evolution(write(tmp_path, "evolution", data), load_towers(towers.TOWERS_FILE))
    return str(err.value)


def test_unknown_field(tmp_path):
    msg = tower_error(tmp_path, lambda t: t["gun"].update(rnage=100))
    assert msg == "towers.json: tower 'gun': unknown fields ['rnage']"


def test_missing_field(tmp_path):
    msg = tower_error(tmp_path, lambda t: t["gun"].pop("damage"))
    assert msg == "towers.json: tower 'gun': missing fields ['damage']"


def test_unknown_palette_color(tmp_path):
    msg = tower_error(tmp_path, lambda t: t["gun"]["look"]["layers"][0].__setitem__(2, "nope"))
    assert msg == "towers.json: tower 'gun': unknown palette color 'nope'"


def test_unknown_shape(tmp_path):
    msg = tower_error(tmp_path, lambda t: t["gun"]["look"]["layers"][0].__setitem__(0, "blob"))
    assert msg.startswith("towers.json: tower 'gun': look needs layers with shapes from")


def test_mechanic_pairs(tmp_path):
    msg = tower_error(tmp_path, lambda t: t["frost"].pop("slow_time"))
    assert msg == "towers.json: tower 'frost': slow and slow_time go together"


def test_broken_json(tmp_path):
    with pytest.raises(ValueError, match=r"^towers\.json: Expecting"):
        load_towers(write(tmp_path, "towers", '{"towers": {,}}'))


def test_tree_names_unknown_tower(tmp_path):
    msg = evolution_error(tmp_path, lambda d: d["lines"]["gun"].update(tier2="rifel"))
    assert msg == "evolution.json: line 'gun': 'rifel' is not in towers.json"


def test_tree_tier_mismatch(tmp_path):
    msg = evolution_error(tmp_path, lambda d: d["lines"]["gun"].update(tier2="cannon"))
    assert msg == "evolution.json: line 'gun': 'cannon' is tier 1 in towers.json, expected tier 2"


def test_tree_needs_two_branches(tmp_path):
    msg = evolution_error(tmp_path, lambda d: d["lines"]["gun"]["tier3"].pop())
    assert msg == "evolution.json: line 'gun': tier3 needs exactly two branches"


def test_final_parents_from_one_line(tmp_path):
    msg = evolution_error(tmp_path, lambda d: d["finals"].update(flak=["minigun", "sniper"]))
    assert msg == "evolution.json: final 'flak': parents must come from different lines"


def test_duplicate_final_pair(tmp_path):
    msg = evolution_error(tmp_path, lambda d: d["finals"].update(flak=["sniper", "bombard"]))
    assert msg == "evolution.json: final 'railgun': sniper + bombard already makes 'flak'"


def test_unreachable_tower(tmp_path):
    msg = evolution_error(tmp_path, lambda d: d["finals"].pop("obsidian"))
    assert msg == "evolution.json: towers that can never be built: ['obsidian']"


def test_line_order_sets_buy_order(tmp_path):
    data = real("evolution")
    data["lines"] = dict(reversed(list(data["lines"].items())))
    order, *_ = load_evolution(write(tmp_path, "evolution", data), load_towers(towers.TOWERS_FILE))
    assert order == ["frost", "cannon", "gun"]


# ---- levels and waves ----------------------------------------------------------
def on_map(x, y):
    return 0 <= x < COLS and 0 <= y < ROWS


def test_twenty_distinct_levels():
    assert len(ALL_LEVELS) == 20
    assert len({t.name for t in THEMES}) == 20
    assert len({tuple(map(tuple, w)) for _, w in ALL_LEVELS}) == 20


def test_a_pass_plays_the_first_ten_levels():
    """Levels 11-20 are kept as a backup; only the first LEVEL_COUNT are played, with their bosses."""
    assert LEVEL_COUNT == 10 and LEVELS == ALL_LEVELS[:10]
    assert BOSS_LEVELS == {10: "warden"} and ALL_BOSS_LEVELS[20] == "overlord"


@pytest.mark.parametrize("n", range(1, 21))
def test_level_path(n):
    """Paths enter and leave off the map, are axis-aligned, and never run alongside themselves.
    Covers the backup levels too, so they still work if they're brought back."""
    theme, wps = ALL_LEVELS[n - 1]
    assert not on_map(*wps[0]) and not on_map(*wps[-1])
    assert all(on_map(*p) for p in wps[1:-1])
    segments = []
    for (x0, y0), (x1, y1) in zip(wps, wps[1:]):
        assert (x0 == x1) != (y0 == y1), "axis aligned"
        segments.append(build_path_cells([(x0, y0), (x1, y1)]))
    for i in range(len(segments)):
        for j in range(i + 2, len(segments)):
            gap = min((abs(a[0] - b[0]) + abs(a[1] - b[1]) for a in segments[i] for b in segments[j]), default=99)
            assert gap >= 2, f"{theme.name}: segments {i} and {j} touch"


@pytest.mark.parametrize("level_idx", range(LEVEL_COUNT))
def test_wave_composition(level_idx):
    """Only the last wave of a level has its elite or boss, and only boss levels have bosses."""
    for wave_idx in range(4):
        kinds, _ = make_wave(level_idx, wave_idx)
        assert not {"elite", "warden", "overlord"} & set(kinds)
    kinds, _ = make_wave(level_idx, 4)
    assert kinds[-1] == BOSS_LEVELS.get(level_idx + 1, "elite")
    assert kinds.count("warden") + kinds.count("overlord") + kinds.count("elite") == 1


def test_waves_get_harder():
    mults = [make_wave(level, wave)[1] for level in range(LEVEL_COUNT) for wave in range(5)]
    assert mults == sorted(mults) and mults[0] == 1
