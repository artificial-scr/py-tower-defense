"""Balance logs: one uniquely named file per level played, with numbers that add up."""

import glob
import json
import os

import pygame
import pytest

import balance_log
import main
from helpers import bot_play, build, key, put, ranked_spots, run_wave


def check_log(path):
    """Cross-check a log file's numbers against each other; returns its data."""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    enemies, by_kind = d["enemies"], d["towers_by_kind"]
    tower_damage = sum(k["damage"] for k in by_kind.values())
    enemy_damage = sum(e["damage_taken"] for e in enemies)
    assert tower_damage == pytest.approx(enemy_damage, abs=1 + 0.1 * len(enemies)), "damage dealt == damage taken"
    killed = [e for e in enemies if e["outcome"] == "killed"]
    assert sum(k["kills"] for k in by_kind.values()) == len(killed)
    assert all(e["killed_by"] for e in killed), "every kill is attributed"
    assert all(e["damage_taken"] == pytest.approx(e["max_hp"], abs=0.2) for e in killed)
    for w in d["waves"]:
        if not w.get("unfinished"):
            assert w["kills"] + w["leaks"] == sum(w["composition"].values()) + w["summoned"], w
    eco = d["economy"]
    assert eco["gold_start"] + sum(eco["earned"].values()) - sum(eco["spent"].values()) == eco["gold_end"]
    assert sum(k["spawned"] for k in d["enemies_by_kind"].values()) == len(enemies)
    ids = [t["id"] for t in d["towers"]]
    assert len(ids) == len(set(ids))
    assert "railgun" in d["specs"]["towers"] and "warden" in d["specs"]["enemies"]
    comp = d["strongest_comp"]
    if comp:
        assert comp["value"] == sum(t["gold_spent"] for t in comp["towers"])
        assert sum(comp["by_kind"].values()) == comp["tower_count"] == len(comp["towers"])
        on_map_at_end = sum(t["gold_spent"] for t in d["towers"] if t["status"] == "active")
        assert comp["value"] >= on_map_at_end, "the end of the level is checked too"
    return d


def log_names(game):
    return sorted(os.path.basename(f) for f in glob.glob(os.path.join(game.log_session.dir, "*.json")))


def test_logs_across_runs(logged_game):
    g = logged_game
    # run 1: the bot clears levels 1-3 (moving and selling towers too), then quits during level 4
    bot_play(g, until_level=4, move_and_sell=True)
    assert g.level_idx == 3 and g.state == "build"
    g.start_wave()
    for _ in range(600):
        g.update(1 / 60)
    g.finish_log("quit")
    # run 2: restart and lose level 1 on purpose
    g.reset()
    g.lives = 1
    g.start_wave()
    run_wave(g)
    assert g.state == "game_over"
    # run 3: restart and quit before any wave: not worth a file
    g.reset()
    g.finish_log("quit")

    assert log_names(g) == ["run01_level01_meadow_cleared.json", "run01_level02_desert_cleared.json",
                            "run01_level03_tundra_cleared.json", "run01_level04_volcano_quit.json",
                            "run02_level01_meadow_lost.json"]
    for name in log_names(g):
        check_log(os.path.join(g.log_session.dir, name))


def test_events_are_logged(logged_game):
    g = logged_game
    bot_play(g, until_level=2, move_and_sell=True)
    d = check_log(os.path.join(g.log_session.dir, log_names(g)[0]))
    types = {e["type"] for e in d["events"]}
    assert {"buy", "fuse", "evolve", "move", "sell"} <= types
    assert d["level"]["outcome"] == "cleared" and d["level"]["waves_started"] == 5


def finish_and_read(g, outcome="quit"):
    with open(g.finish_log(outcome), encoding="utf-8") as f:
        return json.load(f)


def test_strongest_comp_is_the_one_before_a_sell(logged_game):
    g = logged_game
    build(g, "cannon", (1, 1))
    build(g, "gun", (2, 1))
    g.start_wave()
    g.selected = g.towers[(1, 1)]
    g.handle_event(key(pygame.K_s))  # 140 on the map just before the sell
    build(g, "frost", (1, 1))  # back up to 120
    d = finish_and_read(g)
    comp = d["strongest_comp"]
    assert comp["value"] == 140 and comp["trigger"] == "sell"
    assert comp["by_kind"] == {"cannon": 1, "gun": 1} and comp["wave"] == 1 and comp["during_wave"]
    assert [t["kind"] for t in comp["towers"]] == ["cannon", "gun"], "most valuable first"


def test_strongest_comp_at_level_end(logged_game):
    g = logged_game
    build(g, "gun", (1, 1))
    g.selected = g.towers[(1, 1)]
    g.sell_selected()  # 50 before the sell
    build(g, "gun", (1, 1))
    build(g, "gun", (1, 1))  # fused into a rifle: 100
    g.start_wave()
    d = finish_and_read(g)
    comp = d["strongest_comp"]
    assert comp["value"] == 100 and comp["trigger"] == "level_end"
    assert comp["towers"] == [{"id": g.towers[(1, 1)].uid, "kind": "rifle", "tier": 2, "gold_spent": 100,
                               "tile": [1, 1]}]


def test_no_towers_no_comp(logged_game):
    g = logged_game
    g.start_wave()
    assert finish_and_read(g)["strongest_comp"] is None


def test_boss_level_log(logged_game, monkeypatch):
    g = logged_game
    g.load_level(9)
    for tile, kind in zip(ranked_spots(g)[:12], ["railgun", "tesla", "flak", "avalanche"] * 3):
        put(g, kind, tile)
    g.wave_idx = 4
    monkeypatch.setattr(main, "make_wave", lambda level_idx, wave_idx: (["basic", "warden"], 20))
    g.start_wave()
    run_wave(g)
    [name] = log_names(g)
    d = check_log(os.path.join(g.log_session.dir, name))
    assert d["level"]["boss_level"] and d["level"]["number"] == 10 and d["level"]["outcome"] == "cleared"
    assert d["enemies_by_kind"]["warden"]["spawned"] == d["enemies_by_kind"]["warden"]["killed"] == 1
    assert d["waves"][0]["summoned"] == d["enemies_by_kind"]["fast"]["summoned"]


def test_unique_files(tmp_path):
    s1, s2 = balance_log.LogSession(str(tmp_path)), balance_log.LogSession(str(tmp_path))
    assert s1.dir != s2.dir, "two launches in the same second get different folders"
    p1, p2 = s1.write("same", {"a": 1}), s1.write("same", {"a": 2})
    assert p1 != p2 and p2.endswith("same_2.json")
    with open(p1, encoding="utf-8") as f:
        assert json.load(f) == {"a": 1}, "never overwritten"
