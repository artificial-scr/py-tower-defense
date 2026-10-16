"""Tower unlocks: achievements.json, the profile's owned towers, the locks in play, discoveries, the
achievement tracker's conditions, and the unlock card."""

import json
import random
from types import SimpleNamespace

import pygame
import pytest

import achievements
import main
from achievements import (ACHIEVEMENTS, DISCOVERIES, PREREQUISITES, START_TOWERS, AchievementTracker,
                          load_achievements)
from helpers import drag, free_tiles, key, mouse_down, put, px, run_wave
from progress import Profile
from towers import TOWERS


# ---- achievements.json ---------------------------------------------------------------------
def test_every_tower_but_the_start_has_one_achievement():
    assert START_TOWERS == ["gun"] and DISCOVERIES == 2
    unlocked = [a["unlocks"] for a in ACHIEVEMENTS.values()]
    assert sorted(unlocked) == sorted(k for k in TOWERS if k not in START_TOWERS)
    assert ACHIEVEMENTS["frost"]["goals"][1]["scope"] == "ever", "scope defaults to ever"


@pytest.mark.parametrize("change, message", [
    (lambda d: d["achievements"]["rifle"].update(unlocks="laser"), "isn't in towers.json"),
    (lambda d: d["achievements"]["rifle"].update(unlocks="gun"), "which every profile starts with"),
    (lambda d: d["achievements"]["mortar"].update(unlocks="rifle"), "already unlocked by"),
    (lambda d: d["achievements"].pop("obsidian"), "towers no achievement unlocks"),
    (lambda d: d["achievements"]["rifle"]["goals"][0].update(condition="vibes"), "condition must be one of"),
    (lambda d: d["achievements"]["rifle"]["goals"][0].pop("kind"), "missing fields"),
    (lambda d: d["achievements"]["rifle"]["goals"][0].update(colour=1), "unknown fields"),
    (lambda d: d["achievements"]["rifle"]["goals"][0].update(kind="laser"), "isn't a tower"),
    (lambda d: d["achievements"]["frost"]["goals"][1].update(enemy=["dragon"]), "isn't a monster"),
    (lambda d: d["achievements"]["frost"]["goals"][1].update(scope="week"), "scope must be one of"),
    (lambda d: d["achievements"]["dragon"]["goals"][0].update(how="magic"), "how must be one of"),
    (lambda d: d["achievements"]["zero"]["goals"][0].update(only_line="laser"), "isn't a tower line"),
    (lambda d: d.update(start=["rifle"]), "isn't a tier 1 tower"),
])
def test_broken_achievements_file(tmp_path, change, message):
    with open(achievements.ACHIEVEMENTS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    change(data)
    path = tmp_path / "achievements.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=message):
        load_achievements(str(path))


# ---- the profile ------------------------------------------------------------------------------
def test_a_new_profile_owns_the_gun_only(tmp_path):
    p = Profile(str(tmp_path / "p.json"))
    assert p.towers_unlocked == ["gun"] and p.discoveries_left == 2 and p.achievements == {}
    assert p.unlock_tower("cannon") and not p.unlock_tower("cannon"), "only new the first time"
    p.discover("flak")
    p.achievements["frost/1"] = 7
    p.save()
    again = Profile.load(str(tmp_path / "p.json"))
    assert again.towers_unlocked == ["gun", "cannon", "flak"], "kept in towers.json order"
    assert again.new_towers == ["cannon", "flak"] and again.discoveries_left == 1
    assert again.achievements == {"frost/1": 7}
    again.seen_tower("cannon")
    assert Profile.load(str(tmp_path / "p.json")).new_towers == ["flak"]


def test_unknown_towers_are_dropped_and_the_start_towers_kept(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"version": 1, "towers_unlocked": ["laser", "frost"], "new_towers": ["laser"]}))
    p = Profile.load(str(path))
    assert p.towers_unlocked == ["gun", "frost"] and p.new_towers == []


def test_no_damage_cards_for_a_line_that_cant_be_built():
    p = Profile(None)
    drawn = {c for seed in range(200) for c in p.draw_cards("tower", random.Random(seed), 3)}
    assert "sharp_gun" in drawn and not {"sharp_cannon", "sharp_frost"} & drawn
    p.unlock_tower("cannon")
    drawn = {c for seed in range(200) for c in p.draw_cards("tower", random.Random(seed), 3)}
    assert "sharp_cannon" in drawn and "sharp_frost" not in drawn


# ---- locks in play ---------------------------------------------------------------------------
def test_locked_towers_cant_be_bought(locked):
    locked.gold = 1000
    locked.handle_event(key(pygame.K_2))
    assert locked.build_kind is None
    locked.handle_event(key(pygame.K_1))
    assert locked.build_kind == "gun"


def test_two_guns_dont_fuse_until_rifle_is_unlocked(locked):
    a, b = put(locked, "gun", (6, 4)), put(locked, "gun", (8, 4))
    drag(locked, (8, 4), (6, 4))
    assert locked.towers[(6, 4)] is a and locked.towers[(8, 4)] is b and a.kind == "gun"
    locked.build_kind = "gun"
    assert not locked.can_place((6, 4))
    locked.build_kind = None
    locked.profile.unlock_tower("rifle")
    drag(locked, (8, 4), (6, 4))
    assert a.kind == "rifle" and (8, 4) not in locked.towers


def test_a_locked_branch_shows_but_cant_be_picked(locked):
    locked.profile.unlock_tower("rifle")
    a = put(locked, "rifle", (6, 4))
    put(locked, "rifle", (8, 4))
    drag(locked, (8, 4), (6, 4))
    assert a.kind == "rifle" and (8, 4) in locked.towers, "neither branch unlocked: no fusion"
    locked.profile.unlock_tower("sniper")
    drag(locked, (8, 4), (6, 4))
    assert locked.overlay == "choice" and locked.choice[1] == ["minigun", "sniper"]
    locked.handle_event(key(pygame.K_1))  # Minigun: locked
    assert locked.overlay == "choice"
    locked.handle_event(key(pygame.K_2))
    assert locked.overlay is None and a.kind == "sniper"


def test_the_first_two_finals_are_discovered_by_fusing_them(locked):
    for kind in ("minigun", "bombard", "sniper", "incinerator"):
        locked.profile.unlock_tower(kind)
    locked.pending_unlocks.clear()
    pairs = [("minigun", "bombard", "flak"), ("sniper", "incinerator", "solar"), ("minigun", "incinerator", "dragon")]
    for i, (a, b, final) in enumerate(pairs):
        target = put(locked, a, (4 + i * 3, 4))
        put(locked, b, (4 + i * 3, 6))
        drag(locked, (4 + i * 3, 6), (4 + i * 3, 4))
        if i < 2:
            assert target.kind == final and locked.profile.has_tower(final)
            assert locked.pending_unlocks == [{"kind": final, "how": "discovery"}]
            locked.pending_unlocks.clear()  # the card would take the next click
        else:
            assert target.kind == a and not locked.profile.has_tower(final), "no discoveries left"
    assert locked.profile.discoveries_left == 0
    locked.profile.unlock_tower("dragon")
    drag(locked, (10, 6), (10, 4))
    assert locked.towers[(10, 4)].kind == "dragon", "an owned final fuses as before"


# ---- the unlock card ----------------------------------------------------------------------------
def test_four_guns_unlock_the_rifle_and_its_card_shows_at_once(locked):
    locked.gold = 1000
    for tile in free_tiles(locked)[:4]:
        locked.build_kind = "gun"
        locked.handle_event(mouse_down(px(tile)))
        locked.update(1 / 60)
    assert locked.profile.has_tower("rifle")
    assert locked.overlay == "unlock" and locked.pending_unlocks == [{"kind": "rifle", "how": "achievement"}]
    locked.handle_event(key(pygame.K_SPACE))
    assert locked.overlay is None and locked.state == "build", "the key only put the card away"


def test_an_unlock_during_a_wave_waits_for_the_build_phase(locked):
    locked.start_wave()
    locked.tower_unlocked("cannon")
    assert locked.overlay is None
    locked.spawn_queue.clear()
    locked.enemies.clear()
    run_wave(locked)
    assert locked.state == "build" and locked.overlay == "unlock"


def test_unlock_screens_draw(locked):
    """The lock in the panel, the tree, the branch screen and the unlock card draw without errors."""
    locked.draw()
    locked.show_tree = True
    locked.draw()
    locked.show_tree = False
    locked.profile.unlock_tower("rifle")
    locked.profile.unlock_tower("sniper")
    locked.choice = (put(locked, "rifle", (6, 4)), ["minigun", "sniper"])
    locked.draw()
    locked.choice = None
    locked.tower_unlocked("sniper")
    locked.tower_unlocked("flak", "discovery")
    for _ in range(2):
        assert locked.overlay == "unlock"
        locked.draw()
        locked.dismiss_unlock()
    assert locked.tracker.closest() is not None


# ---- the tracker's conditions --------------------------------------------------------------------
@pytest.fixture
def tracked(tmp_path):
    """A tracker on a fresh profile, and the towers it unlocked."""
    unlocked = []
    p = Profile(str(tmp_path / "p.json"))
    return SimpleNamespace(profile=p, tracker=AchievementTracker(p, unlocked.append), unlocked=unlocked)


def own_parents(profile, *kinds):
    """Own every tower `kinds` are fused from, all the way down, so their achievements count."""
    todo = [p for k in kinds for p in PREREQUISITES[k]]
    while todo:
        kind = todo.pop()
        profile.unlock_tower(kind)
        todo += PREREQUISITES[kind]


def dead(kind="basic", by=None, how="direct", slowed=False, escaped=False, spawn_t=0.0, tower=1):
    """A monster that just left the map, killed by a tower of kind `by` (or no tower) or escaped."""
    return SimpleNamespace(kind=kind, escaped=escaped, slowed=slowed, spawn_t=spawn_t, alive=False,
                           killed_by={"tower": tower, "kind": by, "how": how} if by else None)


def test_kills_over_all_time_add_up_across_levels_and_save(tracked):
    for i in range(39):
        tracked.tracker.on_death(dead("fast"), i)
        if i == 20:
            tracked.tracker.start_level()
    assert tracked.profile.achievements["frost/1"] == 39 and not tracked.unlocked
    assert Profile.load(tracked.profile.path).achievements == {}, "written at the next flush, not every kill"
    tracked.tracker.on_death(dead("fast"), 40)
    assert tracked.unlocked == ["frost"]
    tracked.tracker.flush()
    assert Profile.load(tracked.profile.path).achievements["frost/1"] == 40


def test_level_kills_restart_each_level(tracked):
    own_parents(tracked.profile, "incinerator")
    for _ in range(49):
        tracked.tracker.on_death(dead(by="mortar"), 0)
    tracked.tracker.start_level()
    tracked.tracker.on_death(dead(by="mortar"), 0)
    assert "incinerator" not in tracked.unlocked
    assert tracked.profile.achievements["incinerator/0"] == 49, "the best is kept"
    for _ in range(49):
        tracked.tracker.on_death(dead(by="mortar"), 0)
    assert "incinerator" in tracked.unlocked


def test_kill_filters(tracked):
    own_parents(tracked.profile, "sniper", "shatter", "dragon")
    t = tracked.tracker
    t.on_death(dead("basic", by="rifle"), 0)
    t.on_death(dead("tank", by="gun"), 0)
    assert "sniper" not in tracked.unlocked
    t.on_death(dead("elite", by="rifle"), 0)
    assert "sniper" in tracked.unlocked
    for _ in range(29):
        t.on_death(dead(slowed=True, by="frost"), 0)
    t.on_death(dead(slowed=False, by="frost"), 0)
    assert "shatter" not in tracked.unlocked
    t.on_death(dead(slowed=True, by="frost"), 0)
    assert "shatter" in tracked.unlocked
    tracked.profile.achievements["dragon/0"] = 499
    t.on_death(dead(by="incinerator", how="splash"), 0)
    assert "dragon" not in tracked.unlocked
    t.on_death(dead(by="incinerator", how="burn"), 0)
    assert "dragon" in tracked.unlocked


def test_a_leak_unlocks_frost(tracked):
    tracked.tracker.on_death(dead("basic", escaped=True), 0)
    assert not tracked.unlocked and tracked.tracker.leaked
    tracked.tracker.on_death(dead("fast", escaped=True), 0)
    assert tracked.unlocked == ["frost"]


def test_multi_kill_counts_one_towers_kills_in_one_update(tracked, monkeypatch):
    """One Mortar killing 2 or more at once, 20 times over all runs (once the Bombard's goal)."""
    own_parents(tracked.profile, "bombard")
    goal = {"desc": "One Mortar kills 2 monsters at once, 20 times", "condition": "multi_kill", "by": "mortar",
            "kills": 2, "target": 20, "scope": "ever"}
    monkeypatch.setitem(achievements.ACHIEVEMENTS["bombard"], "goals", [goal])
    t = tracked.tracker
    for tower in (1, 1, 1, 2, 3, 3):  # tower 1: 3 kills, tower 2: 1, tower 3: 2
        t.on_death(dead(by="mortar", tower=tower), 0)
    t.on_death(dead(by="mortar", how="burn", tower=2), 0)  # burns aren't a shot
    t.on_death(dead(by="gun", tower=4), 0)
    t.on_death(dead(by="gun", tower=4), 0)
    t.tick([], [], True)
    assert tracked.profile.achievements["bombard/0"] == 2, "two Mortars made a multi-kill"
    t.start_level()  # a new level (or run): the count goes on
    for _ in range(17):
        t.on_death(dead(by="mortar", tower=1), 0)
        t.on_death(dead(by="mortar", tower=1), 0)
        t.tick([], [], True)
    assert "bombard" not in tracked.unlocked and tracked.profile.achievements["bombard/0"] == 19
    assert t.progress("bombard/0", goal) == 19
    t.on_death(dead(by="mortar", tower=5), 0)
    t.on_death(dead(by="mortar", tower=5), 0)
    t.tick([], [], True)
    assert "bombard" in tracked.unlocked


def test_multi_kill_without_kills_is_the_best_single_shot(tracked):
    goal = {"condition": "multi_kill", "by": "mortar", "target": 4, "scope": "ever"}
    assert achievements.is_peak(goal) and not achievements.is_peak({**goal, "kills": 2})


def test_burst_counts_kills_within_its_window(tracked):
    own_parents(tracked.profile, "tesla")
    t = tracked.tracker
    for i in range(24):
        t.on_death(dead(), i * 0.05)
    t.on_death(dead(), 3.0)
    assert "tesla" not in tracked.unlocked
    for i in range(24):
        t.on_death(dead(), 3.0 + i * 0.05)
    assert "tesla" in tracked.unlocked


def test_boss_kill_must_be_quick(tracked):
    own_parents(tracked.profile, "railgun")
    tracked.tracker.on_death(dead("warden", by="gun", spawn_t=0), 21)
    assert "railgun" not in tracked.unlocked
    tracked.tracker.on_death(dead("warden", by="gun", spawn_t=5), 25)
    assert "railgun" in tracked.unlocked


def test_peaks_on_the_map(tracked):
    own_parents(tracked.profile, "blizzard")
    t = tracked.tracker
    tower = SimpleNamespace(kind="gun", pos=pygame.Vector2(0, 0), range=100)
    near = [SimpleNamespace(alive=True, pos=pygame.Vector2(10, 0), slowed=i < 9 or i == 14) for i in range(15)]
    t.tick([tower] * 3, near[:14], True)
    t.updates = achievements.SAMPLE_EVERY - 1
    t.tick([tower] * 3, near[:14], True)
    assert not tracked.unlocked
    t.updates = achievements.SAMPLE_EVERY - 1
    t.tick([tower] * 4, near, True)
    assert set(tracked.unlocked) == {"rifle", "cannon", "blizzard"}


def test_wave_level_and_pass_goals(tracked):
    own_parents(tracked.profile, "breaker", "zero", "hailstorm", "solar", "thermal", "avalanche", "obsidian")
    t = tracked.tracker
    t.on_wave_cleared(59)
    assert not tracked.unlocked
    t.on_wave_cleared(60)
    assert tracked.unlocked == ["breaker"]
    t.tick([SimpleNamespace(kind="frost", pos=pygame.Vector2(), range=1)], [], False)
    t.on_level_cleared(4)
    assert "zero" in tracked.unlocked and "hailstorm" not in tracked.unlocked, "no leaks, but before level 5"
    t.start_level()
    t.on_death(dead(escaped=True), 0)
    t.on_level_cleared(6)
    assert "hailstorm" not in tracked.unlocked
    t.start_level()
    t.on_level_cleared(6)
    assert "hailstorm" in tracked.unlocked
    t.on_pass_won(finale=False, gold=999)
    assert "solar" in tracked.unlocked and not {"thermal", "avalanche", "obsidian"} & set(tracked.unlocked)
    t.on_pass_won(finale=True, gold=1000)
    assert {"thermal", "avalanche"} <= set(tracked.unlocked) and "obsidian" not in tracked.unlocked
    t.on_pass_won(finale=False, gold=0)
    assert "obsidian" in tracked.unlocked


def test_an_achievement_counts_only_once_its_parents_are_owned(tracked):
    p, t = tracked.profile, tracked.tracker
    assert {k for k in TOWERS if t.available(k)} == {"rifle", "cannon", "frost"}
    t.on_death(dead("elite", by="rifle"), 0)
    assert "sniper" not in tracked.unlocked and "sniper/0" not in p.achievements, "no progress either"
    assert t.closest()[0] in ("rifle", "cannon", "frost")
    p.unlock_tower("rifle")
    assert t.available("sniper") and t.missing_prerequisites("flak") == ["minigun", "bombard"]
    t.on_death(dead("elite", by="rifle"), 0)
    assert tracked.unlocked == ["sniper"]


def test_a_tower_unlocked_by_an_event_doesnt_count_it_for_its_children(tracked):
    own_parents(tracked.profile, "minigun")
    for _ in range(100):
        tracked.tracker.on_death(dead(by="rifle"), 0)
    assert tracked.unlocked == ["minigun"] and "flak/0" not in tracked.profile.achievements


def test_the_tree_tells_what_to_unlock_first(locked):
    assert locked.how_to_unlock("sniper") == "Unlock the Rifle first"
    assert locked.how_to_unlock("flak") == "Unlock the Minigun and the Bombard first"
    locked.profile.unlock_tower("rifle")
    assert locked.how_to_unlock("sniper") == ACHIEVEMENTS["sniper"]["goals"][0]["desc"]
    locked.show_tree = True
    locked.draw()


def test_a_level_cleared_in_play_counts(locked):
    """The hooks are wired into the game: a Towers level cleared with only Frost-line towers."""
    own_parents(locked.profile, "zero")
    put(locked, "frost", (6, 4))
    locked.wave_idx = main.WAVES_PER_LEVEL - 1
    locked.start_wave()
    locked.spawn_queue.clear()
    run_wave(locked)
    assert locked.state == "level_complete" and locked.profile.has_tower("zero")


def test_the_monsters_side_counts_nothing(screen, tmp_path):
    (tmp_path / "profile.json").write_text(json.dumps({"version": 1, "milestones": {"starter_pack": True}}))
    g = main.Game(screen, log_dir=None, side="monsters")
    g.budget = 500
    g.draft("fast", 5)
    g.send_wave()
    while g.state == "wave":
        g.update(1 / 60)
    assert g.profile.towers_unlocked == ["gun"] and g.profile.achievements == {}
