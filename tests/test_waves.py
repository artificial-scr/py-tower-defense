"""waves.json loading and validation, the generated waves, and the scouts' counters (waves.py), in the game too."""

import json

import pytest

import main
import waves
from helpers import put, ranked_spots
from levels import BOSS_LEVELS, LEVEL_COUNT, WAVES_PER_LEVEL, tile_center
from waves import (THREAT, add_counters, base_packs, counter_options, load_waves, make_wave, roster, scout, threat,
                   wave_budget)

LEVEL_WAVES = [(level, wave) for level in range(LEVEL_COUNT) for wave in range(WAVES_PER_LEVEL)]
PATH = [(x * 40 + 20, 220) for x in range(20)]  # a straight path along row 5
GOLD = {"gun": 50, "minigun": 200, "chiller": 140, "bombard": 360, "lance": 480, "dragon": 560}  # what each is worth


def bosses(kinds):
    return [k for k in kinds if k in ("elite", "warden", "overlord")]


def report(towers, gold=0, previous=None):
    """Scouts' report on (kind, tile) towers, each worth the gold it takes to build."""
    return scout([(k, GOLD[k], tuple(tile_center(*tile)), 0) for k, tile in towers], gold, PATH, previous)


def lances_in_a_row(n=5, row=4):
    return [("lance", (x, row)) for x in range(n)]


def lances_around(point=0):
    """4 Lances on both sides of the path, all within a Saboteur's reach of one spot on it."""
    return [("lance", (point + dx, row)) for dx in (0, 1) for row in (4, 6)]


def lances_apart(n=5):
    return [("lance", (x * 4, 1)) for x in range(n)]


# ---- the shipped data ----------------------------------------------------------
@pytest.mark.parametrize("level_idx", range(LEVEL_COUNT))
def test_only_the_last_wave_has_its_elite_or_boss(level_idx):
    for wave_idx in range(WAVES_PER_LEVEL - 1):
        assert not bosses(make_wave(level_idx, wave_idx).kinds)
    kinds = make_wave(level_idx, WAVES_PER_LEVEL - 1).kinds
    assert bosses(kinds) == [kinds[-1]] == [BOSS_LEVELS.get(level_idx + 1, "elite")]


def test_waves_get_harder():
    mults = [make_wave(level, wave).hp_mult for level, wave in LEVEL_WAVES]
    assert mults == sorted(mults) and mults[0] == 1
    steps = [b / a for a, b in zip(mults, mults[1:])]
    assert max(steps) < 1.9, "the early boost ramps in over level 1: no wave triples the last"
    assert make_wave(1, 0).hp_mult == 12, "from level 2 on, the full boost"


@pytest.mark.parametrize("level_idx, wave_idx", [(lv, w) for lv, w in LEVEL_WAVES if "waves" not in waves.plan(lv)])
def test_generated_waves_carry_about_their_budget(level_idx, wave_idx):
    """A Juggernaut a level must bring in can push a wave over; nothing falls far short. (Scripted levels are
    tuned by playtests instead.)"""
    kinds = make_wave(level_idx, wave_idx).kinds
    assert 0.85 <= threat(k for k in kinds if k not in bosses(kinds)) / wave_budget(level_idx, wave_idx) <= 1.45


def test_waves_are_the_same_every_time():
    assert all(make_wave(level, wave) == make_wave(level, wave) for level, wave in LEVEL_WAVES)


def test_every_level_brings_its_newcomers_in():
    for level_idx in range(LEVEL_COUNT):
        seen = {k for wave in range(WAVES_PER_LEVEL) for k in make_wave(level_idx, wave).kinds}
        assert set(waves.plan(level_idx)["new"]) <= seen, f"level {level_idx + 1}"
        assert seen - set(bosses(seen)) <= set(roster(level_idx)), "only monsters already brought in"


def test_looters_only_come_as_counters():
    assert "looter" in roster(0)
    assert not any("looter" in make_wave(level, wave).kinds for level, wave in LEVEL_WAVES)


def test_waves_come_in_packs_with_pauses():
    wave = make_wave(0, 1)
    assert wave.kinds == ["basic"] * 6 + ["fast"] * 2 and wave.pauses == {6: waves.RULES["pack_pause"]}


def test_levels_past_the_list_bring_nothing_new():
    assert roster(14) == roster(LEVEL_COUNT - 1) and make_wave(14, 0).kinds


# ---- the scouts ----------------------------------------------------------------
def test_scouts_find_the_tag_holding_most_of_the_gold():
    r = report(lances_apart() + [("gun", (0, 10))])
    assert r["main"] == "single" and r["streak"] == 1 and r["tags"]["light"] == pytest.approx(50 / 2450, abs=1e-3)
    mixed = report([("lance", (0, 1)), ("bombard", (4, 1)), ("dragon", (8, 1)), ("minigun", (12, 1))])
    assert mixed["main"] is None, "no tag at 40% of the gold"
    assert report([])["main"] is None


def test_scouts_weigh_towers_by_the_damage_they_dealt():
    # the first playtest's level 3: three Mortars held most of the gold, one Absolute Zero did most of the work
    towers = [("mortar", 180, (0, 0), 500), ("mortar", 180, (0, 0), 500), ("mortar", 180, (0, 0), 500),
              ("zero", 480, (0, 0), 3000)]
    r = scout(towers, 0, PATH)
    assert r["by"] == "damage" and r["main"] == "slow" and r["value"] == 1020
    nothing_dealt = scout([(k, spent, c, 0) for k, spent, c, _ in towers], 0, PATH)
    assert nothing_dealt["by"] == "gold" and nothing_dealt["main"] == "splash", "no damage yet: by the gold"


def test_the_game_scouts_the_damage_of_the_last_wave_only(game):
    gun = put(game, "gun", ranked_spots(game)[0])
    gun.wave_damage = 999.0
    game.start_wave()
    assert gun.wave_damage == 0
    while game.state == "wave":
        game.update(1 / 60)
    assert game.scout_report["by"] == "damage" and game.scout_report["tags"] == {"light": 1.0}


def test_the_streak_grows_while_the_same_tag_stays_on_top():
    r = report(lances_apart())
    r = report(lances_apart(), previous=r)
    assert r["streak"] == 2
    assert report([("bombard", (0, 1))], previous=r)["streak"] == 1


def test_scouts_count_towers_stacked_by_the_path():
    assert report(lances_in_a_row(3))["cluster"] == report(lances_in_a_row(5))["cluster"] == 3, "60 px: 3 in a row"
    assert report(lances_around())["cluster"] == 4
    assert report(lances_apart())["cluster"] == 0


# ---- counters --------------------------------------------------------------------
@pytest.mark.parametrize("level_idx, wave_idx", [(0, 3), (1, 4), (5, 0)])
def test_no_counters_on_levels_1_2_or_any_first_wave(level_idx, wave_idx):
    assert make_wave(level_idx, wave_idx, report(lances_in_a_row(), gold=10_000)).counter is None


def test_counters_answer_the_main_tag_and_keep_the_threat():
    base = make_wave(8, 3)
    wave = make_wave(8, 3, report(lances_apart()))
    assert wave.counter["tag"] == "single" and wave.counter["reasons"] == ["single-target towers"]
    assert set(wave.counter["added"]) <= set(counter_options(report(lances_apart()), roster(8)))
    assert "swarmling" in wave.counter["added"], "the hardest monster for single-target towers"
    assert threat(wave.kinds) == pytest.approx(threat(base.kinds), abs=max(THREAT.values()))
    assert sum(threat([k] * n) for k, n in wave.counter["added"].items()) >= 0.4 * threat(base.kinds[:-1]) * 0.8


def test_counters_escalate_while_the_build_stays_the_same():
    r = report(lances_apart())
    shares = []
    for _ in range(6):
        shares.append(make_wave(8, 3, r).counter["share"])
        r = report(lances_apart(), previous=r)
    assert shares == pytest.approx([0.4, 0.45, 0.5, 0.55, 0.6, 0.6])


@pytest.mark.parametrize("tag", waves.COUNTERS["tags"])
def test_counters_only_use_monsters_already_brought_in(tag):
    kind = waves.COUNTERS["tags"][tag]["towers"][0]
    r = scout([(kind, 500, (0, 0), 0)] * 3, 0, PATH)
    for level, wave in LEVEL_WAVES:
        counter = make_wave(level, wave, r).counter
        assert not counter or set(counter["added"]) <= set(roster(level))
    assert "juggernaut" not in make_wave(2, 3, r).kinds, "Juggernauts come in on level 4"


def test_stacked_towers_draw_saboteurs_once_they_are_brought_in():
    assert make_wave(4, 3, report(lances_around())).counter["added"].get("saboteur") is None
    added = make_wave(5, 3, report(lances_around())).counter["added"]
    assert added["saboteur"] == 2, "4 towers: the larger count"
    assert make_wave(5, 3, report(lances_in_a_row(3))).counter["added"]["saboteur"] == 1


@pytest.mark.parametrize("gold, looters", [(3000, 0), (3675, 1), (7350, 2), (50_000, 3)])
def test_banked_gold_draws_a_few_looters_into_the_heaviest_pack(gold, looters):
    """5 Lances are worth 2,450: one Looter per 1.5x that banked, 3 at most."""
    r = report(lances_apart(), gold=gold)
    packs, counter = add_counters(base_packs(4, 2, waves.random.Random(0)), 4, 2, r)
    found = [p for p in packs if "looter" in p.kinds]
    assert sum(p.kinds.count("looter") for p in packs) == looters
    if looters:
        assert counter["reasons"][-1] == "banked gold" and len(found) == 1
        heaviest = found[0].kinds
        assert threat(heaviest) == max(threat(p.kinds) for p in packs)
        spots = [i for i, k in enumerate(heaviest) if k == "looter"]
        assert 0 < spots[0] and spots[-1] < len(heaviest) - 1, "in the middle, never first or last"


@pytest.mark.parametrize("tag, best", [("single", ["swarmling", "splitter", "fast"]), ("slow", ["healer", "juggernaut"]),
                                       ("splash", ["elite", "bearer", "fast"]), ("light", ["armored", "swarmling"])])
def test_counters_are_the_main_tags_hardest_monsters(tag, best):
    kind = waves.COUNTERS["tags"][tag]["towers"][-1]
    assert counter_options(scout([(kind, 500, (0, 0), 0)], 0, PATH), roster(9)) == best
    assert counter_options(report([]), roster(9)) == [], "no tag on top: no counters"


def test_counters_keep_monsters_that_already_counter_the_towers():
    for level, wave in [(lv, w) for lv in range(2, LEVEL_COUNT) for w in range(1, WAVES_PER_LEVEL)]:
        r = report(lances_apart())
        base, countered = make_wave(level, wave).kinds, make_wave(level, wave, r).kinds
        for kind in counter_options(r, roster(level)):
            assert countered.count(kind) >= base.count(kind)


def test_a_counter_swarm_comes_as_one_burst():
    kinds = make_wave(8, 3, report(lances_apart())).kinds
    first = kinds.index("swarmling")
    assert kinds[first:first + kinds.count("swarmling")] == ["swarmling"] * kinds.count("swarmling")


def test_counters_take_whole_pattern_repeats():
    """Counters never split a pattern: what's left of each pattern pack is whole repeats of it."""
    rng = waves.random.Random(8 * WAVES_PER_LEVEL + 3)
    before = base_packs(8, 3, rng)
    packs, _ = add_counters(before, 8, 3, report(lances_apart()))
    for p in packs:
        if p.block:
            assert len(p.kinds) % p.block == 0 and p.kinds == p.kinds[:p.block] * (len(p.kinds) // p.block)


# ---- in the game -----------------------------------------------------------------
def test_packs_pause_between_them_in_the_game(game):
    game.wave_idx = 1
    game.start_wave()
    while game.wave_spawned < 6:
        game.update(1 / 60)
    assert game.spawn_timer == waves.RULES["pack_pause"]


def test_scouts_report_after_each_wave_and_the_preview_shows_the_counters(screen, tmp_path):
    g = main.Game(screen, log_dir=str(tmp_path))
    g.load_level(8)
    for tile in ranked_spots(g)[:5]:
        put(g, "lance", tile).spent = 480
    g.wave_idx = 3
    g.scout_towers()
    assert g.scout_report["main"] == "single"
    recorded, wave = g.next_wave()
    assert recorded is None and wave.counter["tag"] == "single"
    assert any("Scouts saw your" in p.text for p in g.popups)
    g.draw()  # the preview with the scouts' line
    g.start_wave()
    assert g.spawn_queue == wave.kinds and g.wave_counter == wave.counter
    assert g.log.current_wave()["counter"] == wave.counter and g.log.current_wave()["scouted"]["main"] == "single"
    g.draw()  # the preview of what's still to come


def test_monster_records_get_no_counters(game):
    game.profile.monster_records["9"] = {"4": {"value": 50, "queue": ["tank"] * 5, "hp_mult": 3, "mods": {},
                                               "casts": []}}
    game.load_level(8)
    for tile in ranked_spots(game)[:5]:
        put(game, "lance", tile)
    game.wave_idx = 3
    game.scout_towers()
    recorded, wave = game.next_wave()
    assert recorded and wave.kinds == ["tank"] * 5 and wave.counter is None


# ---- a broken file ---------------------------------------------------------------
def shipped():
    with open(waves.WAVES_FILE, encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("change, message", [
    (lambda d: d.pop("budget"), "missing fields ['budget']"),
    (lambda d: d["threat"].update(ghost=3), "'ghost' isn't a monster"),
    (lambda d: d["threat"].update(warden=3), "'warden' isn't a monster"),
    (lambda d: d["levels"][0]["new"].append("juggernaut"), "level 4: 'juggernaut' is already on the roster"),
    (lambda d: d["levels"][0]["waves"].pop(), "scripts 5 waves or none"),
    (lambda d: d["levels"][0]["waves"][0].append([["tank", 2]]), "['tank'] aren't on the roster yet"),
    (lambda d: d["levels"][0]["waves"][0][0].append(["basic", 0]), "count 1 or more"),
    (lambda d: d["roles"][0]["slots"].append(["stream", 0.5]), "slot shares must add up to 1"),
    (lambda d: d["roles"][0]["slots"][0].__setitem__(0, "boss"), "slots must be"),
    (lambda d: d["patterns"].pop("stream"), "needs a 'stream' pattern"),
    (lambda d: d["counters"]["tags"]["light"]["towers"].append("rifle"), "every tower needs exactly one tag"),
    (lambda d: d["counters"]["tags"]["light"]["towers"].remove("gun"), "every tower needs exactly one tag"),
    (lambda d: d["counters"]["tags"]["single"]["towers"].append("ballista"), "['ballista'] aren't towers"),
    (lambda d: d["counters"]["role_weight"].pop("finale"), "one weight for each role"),
    (lambda d: d["counters"]["scores"].pop("burn"), "scores needs one table for each tag"),
    (lambda d: d["counters"]["scores"]["burn"].update(ghost=2), "'ghost' has no threat"),
    (lambda d: d["counters"].update(options=0), "options a whole number"),
    (lambda d: d["counters"]["hoard"].update(kind="ghost"), "'ghost' has no threat"),
])
def test_broken_waves_file(tmp_path, change, message):
    data = shipped()
    change(data)
    path = tmp_path / "waves.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=message.replace("[", r"\[").replace("]", r"\]")):
        load_waves(str(path))
