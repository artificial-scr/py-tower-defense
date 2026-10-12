"""Comps per wave, the tower records they become, and the permanent profile."""

import json
import os

import pytest

import main
from graphics import CastWarning
from helpers import build, put, run_wave
from progress import Profile
from towers import NO_TOWER_MODS


def clear_level(game):
    """Play out all the waves left, with towers strong enough to win."""
    while game.state in ("build", "wave"):
        game.start_wave()
        game.hp_mult = 0.01
        run_wave(game)


# ---- comps per wave --------------------------------------------------------------
def test_build_phase_counts_toward_the_next_wave(game):
    build(game, "gun", (1, 1))
    game.selected = game.towers[(1, 1)]
    game.sell_selected()  # before wave 1
    assert game.comps_by_wave[1]["value"] == 50 and not game.comps_by_wave[1]["during_wave"]


def test_each_wave_keeps_its_own_peak(game):
    build(game, "cannon", (1, 1))
    game.start_wave()
    run_wave(game)  # wave 1 ends with a cannon (90)
    game.selected = game.towers[(1, 1)]
    game.sell_selected()
    build(game, "gun", (1, 1))
    game.start_wave()
    run_wave(game)  # wave 2: 90 just before the sell, 50 at the end
    assert game.comps_by_wave[1]["value"] == 90 and game.comps_by_wave[1]["trigger"] == "wave_end"
    assert game.comps_by_wave[2]["value"] == 90 and game.comps_by_wave[2]["trigger"] == "sell"
    assert game.strongest_comp["value"] == 90 and game.strongest_comp["wave"] == 1, "a tie keeps the earlier one"


def test_comps_by_wave_are_logged(logged_game):
    g = logged_game
    build(g, "gun", (1, 1))
    g.start_wave()
    run_wave(g)
    with open(g.finish_log("quit"), encoding="utf-8") as f:
        d = json.load(f)
    assert d["strongest_comp_by_wave"]["1"]["value"] == 50
    assert set(d["strongest_comp_by_wave"]) == {"1", "2"}, "quitting in the build phase closes wave 2's window"


# ---- tower records ---------------------------------------------------------------
def test_clearing_a_level_writes_its_tower_record(game):
    put(game, "railgun", (1, 1)).spent = 1000
    clear_level(game)
    record = game.profile.tower_record(1)
    assert sorted(record) == [1, 2, 3, 4, 5]
    assert record[1]["value"] == 1000 and record[1]["mods"] == NO_TOWER_MODS
    assert record[1]["towers"] == [{"kind": "railgun", "tile": [1, 1], "gold_spent": 1000}]
    with open(main.PROFILE_FILE, encoding="utf-8") as f:
        assert json.load(f)["tower_records"]["1"]["5"]["value"] == 1000


def test_losing_writes_no_record(game):
    game.lives = 1
    put(game, "gun", (0, 0))
    game.start_wave()
    run_wave(game)
    assert game.state == "game_over" and game.profile.tower_record(1) == {}


def test_only_stronger_slots_replace_a_record(tmp_path):
    p = Profile(str(tmp_path / "p.json"))
    comp = lambda value: {"value": value, "towers": [{"kind": "gun", "tile": [1, 1], "gold_spent": value}]}  # noqa: E731
    assert p.record_towers(3, {1: comp(100), 2: comp(100)}) == [1, 2]
    assert p.record_towers(3, {1: comp(100), 2: comp(150), 3: comp(10)}) == [2, 3], "a tie keeps the old one"
    assert p.record_towers(3, {1: comp(40)}) == []
    assert {w: s["value"] for w, s in Profile.load(p.path).tower_record(3).items()} == {1: 100, 2: 150, 3: 10}


# ---- profile file ----------------------------------------------------------------
def test_missing_or_broken_profiles_start_fresh(tmp_path):
    path = str(tmp_path / "p.json")
    assert Profile.load(path).tower_records == {}
    for content in ("not json", "[]", '{"version": 999, "tower_records": {"1": {}}}'):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        assert Profile.load(path).tower_records == {}, content


def test_profile_is_written_atomically(tmp_path):
    (tmp_path / "own").mkdir()
    p = Profile(str(tmp_path / "own" / "p.json"))
    p.record_towers(1, {1: {"value": 5, "towers": []}})
    assert os.listdir(tmp_path / "own") == ["p.json"]


# ---- the Towers side against monster records ---------------------------------------
def monster_wave(queue, casts=(), hp_mult=1.0, mods=None):
    return {"value": sum(main.ENEMY_TYPES[k]["cost"] for k in queue), "queue": list(queue), "hp_mult": hp_mult,
            "mods": mods or {}, "casts": list(casts)}


def test_recorded_wave_replaces_the_generated_one(game):
    game.profile.monster_records["1"] = {"1": monster_wave(["armored", "healer"], hp_mult=3, mods={"hp": 1.2})}
    game.start_wave()
    assert game.spawn_queue == ["armored", "healer"] and game.hp_mult == 3
    game.update(1 / 60)
    assert game.enemies[0].max_hp == pytest.approx(70 * 3 * 1.2)


def test_missing_slots_use_generated_waves(game):
    game.profile.monster_records["1"] = {"2": monster_wave(["tank"])}
    game.start_wave()
    assert "basic" in game.spawn_queue
    run_wave(game)
    game.start_wave()
    assert game.spawn_queue == ["tank"]


def test_recorded_abilities_are_announced_then_cast(game):
    gun = put(game, "gun", (6, 4))
    cast = {"ability": "emp", "t": 2.0, "pos": [int(gun.pos.x), int(gun.pos.y)]}
    shout = {"ability": "frenzy", "t": 2.0, "pos": None}
    game.profile.monster_records["1"] = {"1": monster_wave(["tank"] * 3, casts=[cast, shout])}
    game.start_wave()
    for _ in range(59):
        game.update(1 / 60)
    assert not any(isinstance(e, CastWarning) for e in game.effects)
    game.update(1 / 60)  # 1 s before the cast
    assert any(isinstance(e, CastWarning) for e in game.effects) and not gun.disabled
    assert any("Frenzy" in p.text for p in game.popups)
    for _ in range(61):
        game.update(1 / 60)
    assert gun.disabled and all(e.haste_timer > 0 for e in game.enemies) and game.replay == []


def test_unknown_kinds_and_abilities_in_a_record_are_skipped(game):
    game.profile.monster_records["1"] = {"1": monster_wave(["basic"], casts=[{"ability": "gone", "t": 1, "pos": None}])}
    game.profile.monster_records["1"]["1"]["queue"].append("dragonfly")
    game.start_wave()
    assert game.spawn_queue == ["basic"] and game.replay == []


def test_kill_gold_is_the_monster_cost(game):
    put(game, "railgun", (6, 4))
    game.profile.monster_records["1"] = {"1": monster_wave(["swarmling"])}
    gold = game.gold
    game.start_wave()
    run_wave(game)
    assert game.gold == gold + 2 + 25, "cost + wave bonus"


def test_a_won_monsters_level_comes_back_on_the_towers_side(screen):
    attacker = main.Game(screen, log_dir=None, side="monsters")
    attacker.profile.unlock("monster", "frenzy")
    attacker.load_level(0)
    attacker.budget = 200
    attacker.draft("fast", 30)
    attacker.send_wave()
    attacker.update(1 / 60)
    attacker.cast("frenzy")
    while attacker.state == "wave":
        attacker.update(1 / 60)
    assert attacker.state == "victory", "30 Fast monsters past no towers take all 20 lives"

    defender = main.Game(screen, log_dir=None)  # same profile file
    defender.start_wave()
    assert defender.spawn_queue == ["fast"] * 30 and [c["ability"] for c in defender.replay] == ["frenzy"]
