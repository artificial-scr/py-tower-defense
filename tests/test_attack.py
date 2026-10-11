"""The Monsters side: the defender from a tower record, drafting, abilities, winning and losing."""

import json
import os

import pygame
import pytest

import graphics
import main
from attack import QUEUE_MAX
from graphics import SCALES
from helpers import key, mouse_down, scaled
from levels import WAVES_PER_LEVEL, wave_value


def comp(*towers):
    """A tower record slot from (kind, tile, gold) triples."""
    return {"value": sum(g for _, _, g in towers),
            "towers": [{"kind": k, "tile": list(t), "gold_spent": g} for k, t, g in towers]}


@pytest.fixture
def attack(screen):
    """A Monsters-side game at level 1 against a two-wave tower record."""
    g = main.Game(screen, log_dir=None, side="monsters")
    g.profile.tower_records["1"] = {"1": comp(("gun", (6, 4), 50)),
                                    "3": comp(("rifle", (6, 4), 100), ("cannon", (7, 4), 90))}
    g.load_level(0)
    return g


def play_wave(g, max_frames=100_000):
    g.send_wave()
    for _ in range(max_frames):
        if g.state != "wave":
            return
        g.update(1 / 60)
    raise AssertionError("wave never ended")


# ---- the defender -----------------------------------------------------------------
def test_defender_grows_wave_by_wave(attack):
    g = attack
    assert [t.kind for t in g.towers.values()] == ["gun"] and g.lives == 20
    play_wave(g)  # nothing sent: the wave ends at once
    assert [t.kind for t in g.towers.values()] == ["gun"], "no slot for wave 2: wave 1's comp stays"
    play_wave(g)
    assert sorted(t.kind for t in g.towers.values()) == ["cannon", "rifle"]


def test_no_record_means_no_towers(screen):
    g = main.Game(screen, log_dir=None, side="monsters")
    assert g.towers == {}


# ---- budget and draft ----------------------------------------------------------------
def test_budget_is_the_generated_wave_value_and_carries_over(attack):
    g = attack
    assert g.budget == wave_value(0, 0) == 40
    g.draft("basic", 2)
    play_wave(g)
    assert g.budget == 40 - 10 + wave_value(0, 1)


def test_war_chest_raises_the_budget(screen):
    g = main.Game(screen, log_dir=None, side="monsters")
    g.profile.unlock("monster", "war_chest")
    g.profile.unlock("monster", "war_chest")
    g.load_level(0)
    assert g.budget == round(40 * 1.3)


def test_draft_and_undraft(attack):
    g = attack
    g.draft("tank", 5)
    assert g.queue == ["tank"] * 3 and g.budget == 4, "stops when the budget runs out"
    g.undraft()
    assert g.queue == ["tank"] * 2 and g.budget == 16
    g.draft("armored")
    assert "armored" not in g.queue, "locked kinds can't be drafted"


def test_draft_keys(attack, monkeypatch):
    g = attack
    g.handle_event(key(pygame.K_2))
    assert g.queue == ["fast"]
    monkeypatch.setattr(pygame.key, "get_mods", lambda: pygame.KMOD_SHIFT)
    g.handle_event(key(pygame.K_1))
    assert g.queue == ["fast"] + ["basic"] * 5
    g.handle_event(key(pygame.K_BACKSPACE))
    assert len(g.queue) == 5


def test_draft_by_clicking_the_panel(attack):
    g = attack
    (kind, rect), *_ = g.attack_rows()
    g.handle_event(mouse_down(rect.center))
    assert g.queue == [kind]


def test_clicking_a_queue_icon_removes_it(attack):
    g = attack
    g.draft("basic")
    g.draft("fast")
    (_, center), _ = g.queue_icons()
    g.handle_event(mouse_down((int(center.x), int(center.y))))
    assert g.queue == ["fast"]


def test_unlocked_kinds_join_the_draft(attack):
    g = attack
    g.profile.unlock("monster", "armored")
    assert "armored" in g.draftable()


def test_boss_only_in_a_boss_levels_last_wave(screen):
    g = main.Game(screen, log_dir=None, side="monsters")
    g.load_level(9)
    assert "warden" not in g.draftable()
    g.wave_idx = WAVES_PER_LEVEL - 1
    assert "warden" in g.draftable()
    g.budget = 10_000
    g.draft("warden", 2)
    assert g.queue == ["warden"], "one boss per wave"


def test_queue_is_capped(attack):
    g = attack
    g.budget = 10_000
    g.draft("basic", QUEUE_MAX + 5)
    assert len(g.queue) == QUEUE_MAX


# ---- waves --------------------------------------------------------------------------
def test_sent_wave_uses_buffs_and_the_wave_strength(attack):
    g = attack
    g.profile.unlock("monster", "thick_hide")
    g.draft("basic")
    g.send_wave()
    g.update(1 / 60)
    (e,) = g.enemies
    assert e.max_hp == pytest.approx(30 * 1.0 * 1.1)
    assert g.sent_waves[1]["queue"] == ["basic"] and g.sent_waves[1]["value"] == 5


def test_monsters_side_earns_no_gold(attack):
    g = attack
    gold = g.gold
    g.draft("basic", 8)
    play_wave(g)
    assert g.gold == gold


# ---- abilities ----------------------------------------------------------------------
def test_area_ability_aims_then_casts_on_click(attack):
    g = attack
    g.profile.unlock("monster", "emp")
    g.load_level(0)
    g.draft("tank")
    g.send_wave()
    for _ in range(90):
        g.update(1 / 60)
    g.handle_event(key(pygame.K_1))
    assert g.aiming == "emp"
    gun = g.towers[(6, 4)]
    g.handle_event(mouse_down((int(gun.pos.x), int(gun.pos.y))))
    assert gun.disabled and g.aiming is None and g.cooldowns["emp"] == 20
    (cast,) = g.sent_waves[1]["casts"]
    assert cast["ability"] == "emp" and cast["t"] == pytest.approx(1.5) and cast["pos"] == [260, 180]
    g.handle_event(key(pygame.K_1))
    assert g.aiming is None, "still cooling down"


def test_right_click_cancels_aiming(attack):
    g = attack
    g.profile.unlock("monster", "smoke")
    g.load_level(0)
    g.draft("basic")
    g.send_wave()
    g.cast("smoke")
    g.handle_event(mouse_down((100, 100), button=3))
    assert g.aiming is None and g.cooldowns["smoke"] == 0


def test_instant_ability_and_cooldown_in_game_time(attack):
    g = attack
    g.profile.unlock("monster", "frenzy")
    g.profile.unlock("monster", "frenzy")  # rank 2: 15% shorter cooldown
    g.load_level(0)
    g.draft("basic", 3)
    g.send_wave()
    for _ in range(60):
        g.update(1 / 60)
    g.handle_event(key(pygame.K_1))
    assert all(e.haste_timer > 0 for e in g.enemies)
    assert g.cooldowns["frenzy"] == pytest.approx(25 * 0.85)
    g.speed = 10
    for _ in range(60):
        g.update(1 / 60)
    assert g.cooldowns["frenzy"] == pytest.approx(25 * 0.85 - 1)


def test_no_abilities_outside_a_wave(attack):
    g = attack
    g.profile.unlock("monster", "mend")
    g.load_level(0)
    g.cast("mend")
    assert g.cooldowns["mend"] == 0


# ---- winning and losing ---------------------------------------------------------------
def test_draining_the_lives_wins_and_records_the_waves(attack):
    g = attack
    g.towers = {}
    g.budget = 200
    g.draft("basic", 20)
    play_wave(g)
    assert g.state == "level_complete" and g.lives == 0
    record = g.profile.monster_record(1)
    assert list(record) == [1] and record[1]["value"] == 100 and record[1]["queue"] == ["basic"] * 20
    assert g.enemies == [] and g.spawn_queue == []


def test_towers_holding_after_the_last_wave_loses(attack):
    g = attack
    for _ in range(WAVES_PER_LEVEL):
        play_wave(g)
    assert g.state == "game_over" and g.profile.monster_record(1) == {}


def test_next_level_on_the_monsters_side(attack):
    g = attack
    g.state = "level_complete"
    g.advance()
    assert g.level_idx == 1 and g.side == "monsters" and g.lives == 20 and g.budget == wave_value(1, 0)


def test_no_tower_actions_on_the_monsters_side(attack, mouse):
    g = attack
    gun = g.towers[(6, 4)]
    g.handle_event(mouse_down((int(gun.pos.x), int(gun.pos.y))))
    assert g.selected is gun and g.dragging is None
    g.handle_event(key(pygame.K_s))
    assert (6, 4) in g.towers, "can't sell the defender's towers"
    for b in g.tower_buttons.values():
        g.handle_event(mouse_down((b.rect.right - 2, b.rect.bottom - 2)))
    assert g.build_kind is None


def test_monsters_side_logs(screen, tmp_path):
    g = main.Game(screen, log_dir=str(tmp_path / "logs"), side="monsters")
    g.towers = {}
    g.budget = 200
    g.draft("basic", 20)
    play_wave(g)
    (name,) = os.listdir(g.log_session.dir)
    assert name == "run01_monsters_level01_meadow_cleared.json"
    with open(os.path.join(g.log_session.dir, name), encoding="utf-8") as f:
        d = json.load(f)
    assert d["level"]["side"] == "monsters" and d["waves"][0]["composition"] == {"basic": 20}


# ---- drawing --------------------------------------------------------------------------
@pytest.mark.parametrize("scale", SCALES)
def test_monsters_side_screens_draw(screen, scale, mouse):
    graphics.set_scale(scale)
    g = main.Game(pygame.display.set_mode(graphics.window_size()), log_dir=None, side="monsters")
    for card in ("armored", "healer", "phantom", "emp", "frenzy"):
        g.profile.unlock("monster", card)
    g.profile.tower_records["1"] = {"1": comp(("gun", (6, 4), 50))}
    g.load_level(0)
    mouse[:] = scaled((300, 200), scale)
    g.draft("armored")
    g.draft("phantom")
    g.draw()
    g.send_wave()
    for _ in range(200):
        g.update(1 / 60)
    g.cast("emp")
    g.draw()
    g.cast("emp", pygame.Vector2(260, 180))
    g.cast("frenzy")
    g.draw()
    for state in ("level_complete", "game_over", "victory"):
        g.state = state
        g.draw()


# ---- budget share and starter pack ---------------------------------------------------------
def test_budget_claims_a_share_of_the_defenders_comp(screen):
    g = main.Game(screen, log_dir=None, side="monsters")
    g.profile.tower_records["1"] = {"1": comp(("railgun", (6, 4), 1000))}
    g.load_level(0)
    assert g.share == pytest.approx(main.BUDGET["share_start"])
    assert g.budget == round(1000 * g.share), "the share beats the generated wave's 40"


def test_each_monsters_win_grows_the_share_for_the_run(attack):
    g = attack
    g.towers = {}
    g.budget = 200
    g.draft("basic", 20)
    play_wave(g)
    g.reward_cards = []
    assert g.monster_wins == 1 and g.share == pytest.approx(main.BUDGET["share_start"] + main.BUDGET["share_per_win"])
    g.advance()
    assert main.load_save()["monster_wins"] == 1
    g.end_run()
    assert g.monster_wins == 0, "a new run starts over"


def test_starter_pack_the_first_time_only(screen):
    with open(main.PROFILE_FILE, "w", encoding="utf-8") as f:
        f.write('{"version": 1}')
    g = main.Game(screen, log_dir=None, side="monsters")
    picks = 0
    while g.reward_cards:
        assert g.reward_pool == "monster" and g.frozen
        g.handle_event(key(pygame.K_1))
        picks += 1
    assert picks == main.BUDGET["starter_picks"] and sum(g.profile.unlocks["monster"].values()) == picks
    assert g.profile.milestones["starter_pack"]
    g.load_level(1)
    assert g.reward_cards == []
