"""The bot player (bot.py): its score, its plans, its fusions and its branch picks. The bot's games are in
test_playthrough.py (slow); these check the decisions on a map set up by hand."""

import random
from collections import Counter

import pytest

from bot import PROFILES, Bot, frost_share
from helpers import put
from towers import TOWERS


def test_overkill_doesnt_count(game):
    """Level 1's monsters have about 30 hp: a Sniper's 160 damage counts as 30 a shot, a Minigun's 14 in full."""
    bot = Bot(game)
    bot.update_dps()
    assert bot.dps["sniper"] == pytest.approx(TOWERS["sniper"]["rate"] * bot.monster_hp())
    assert bot.dps["minigun"] == pytest.approx(TOWERS["minigun"]["rate"] * TOWERS["minigun"]["damage"])
    game.load_level(6)
    bot.update_dps()
    assert bot.dps["sniper"] == pytest.approx(TOWERS["sniper"]["rate"] * TOWERS["sniper"]["damage"]), "level 7: in full"


def test_range_reaches_more_path(game):
    bot = Bot(game)
    bot.update_dps()
    near, far = bot.best_free(TOWERS["gun"]["range"]), bot.best_free(TOWERS["sniper"]["range"])
    assert len(bot.covered(far, 240)) > len(bot.covered(near, 240)), "placed for its own range"
    assert bot.score([("sniper", far)]) > bot.score([("sniper", near)])


def test_slowing_stretches_the_path_it_covers(game):
    bot = Bot(game)
    bot.update_dps()
    tile = bot.best_free(110)
    alone = bot.score([("gun", tile)])
    assert bot.score([("gun", tile), ("frost", tile)]) - bot.score([("frost", tile)]) > alone


def test_plans_use_the_towers_on_the_map(game):
    bot = Bot(game)
    bot.update_dps()
    sniper = put(game, "sniper", bot.best_free(240))
    used, buy = bot.recipe("zero", [sniper])
    assert used == [sniper] and Counter(buy) == {"frost": 4}, "a Blizzard to make: 4 Frosts"
    assert bot.recipe("sniper", [sniper]) == ([], ["gun"] * 4), "a target is never a tower already there"


def test_a_plan_names_the_next_piece_and_waits_for_the_gold(game):
    bot = Bot(game)
    game.gold = 0
    bot.step()
    assert bot.target and bot.next_kind in ("gun", "cannon", "frost") and not game.towers
    assert bot.next_kind in {k for k in [bot.target] + list(TOWERS) if TOWERS[k]["tier"] == 1}
    game.gold = TOWERS[bot.next_kind]["cost"]
    kind = bot.next_kind
    bot.step()
    assert [t.kind for t in game.towers.values()] == [kind] and bot.dirty, "bought: plan again"


def test_lines_keep_the_plans_to_them(game):
    bot = Bot(game, lines=("gun",))
    bot.update_dps()
    for kind, buy, _, _ in bot.options():
        assert set(buy) == {"gun"} and "gun" in kind or kind in ("rifle", "minigun", "sniper")


def test_wide_aims_no_higher_than_tier_2(game):
    bot = Bot(game, "wide")
    bot.update_dps()
    assert max(TOWERS[k]["tier"] for k, *_ in bot.options()) == 2


def test_it_fuses_off_plan_only_for_a_gain(game):
    bot = Bot(game)
    bot.score = len  # every tower counts 1: a fusion only ever loses score
    put(game, "gun", (2, 2))
    put(game, "gun", (3, 2))
    bot.target = "cannon"
    assert not bot.fuse_once() and len(game.towers) == 2
    bot.target = "sniper"
    assert bot.fuse_once() and [t.kind for t in game.towers.values()] == ["rifle"], "on the way to the plan"


def test_branches_lean_to_the_stronger_one(game):
    """Two Rifles: Minigun or Sniper, weighted by the square of what each adds."""
    picks = Counter()
    for seed in range(60):
        random.seed(seed)
        game.towers = {}
        game.choice = None
        bot = Bot(game)
        bot.update_dps()
        tile = bot.best_free(130)
        put(game, "rifle", tile)
        game.choice = (game.towers[tile], ["minigun", "sniper"])
        bot.choose()
        picks[game.towers[tile].kind] += 1
    bot.update_dps()
    rest = bot.score([])
    gains = {k: bot.score([(k, tile)]) - rest for k in ("minigun", "sniper")}
    strong = max(gains, key=gains.get)
    assert picks[strong] > picks[min(gains, key=gains.get)] > 0, "mostly the stronger, not always"


def test_every_profile_plans(game):
    for name in PROFILES:
        game.towers = {}
        bot = Bot(game, name)
        bot.step()
        assert bot.next_kind in ("gun", "cannon", "frost"), name


def test_frost_share_counts_frost_based_towers():
    stats = {"levels": [{"towers": ["zero", "railgun"], "frost_based": 1}, {"towers": ["frost"], "frost_based": 1}]}
    assert frost_share(stats) == pytest.approx(2 / 3)
