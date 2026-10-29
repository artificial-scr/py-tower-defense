# Roguelike mode: design and plan

Status: **built** (phases 0–6, 2026-10-11). The open questions were settled along the way; see each
section, and [Balance findings](#9-balance-findings) for why the budget rule changed.

## 1. The loop

A **run** is a series of **passes**. A pass is all 10 levels played from one side.

```
Pass 1: Towers  L1 ... L10  ──beat L10──▶  Pass 2: Monsters  L1 ... L10  ──beat L10──▶  Pass 3: Towers ...
         │                                          │
         └──── lose any level ──▶  RUN OVER  ◀──────┘
                                       │
                                       ▼
                 New run: pick a side (only once Towers L10 has been beaten for the first time)
```

- **Towers side:** the game as it is today: build, fuse, survive 5 waves.
- **Monsters side:** the towers are your recorded comp for that level, and you draft the waves
  that have to break it.
- Each pass you clear sets the records the next pass plays against, so every pass faces your
  own previous best.
- Losing ends the run. Unlocks are kept forever.
- There's no final victory screen any more. Beating Monsters L10 sends you back to Towers L1, and a
  run goes on until you lose. Your score is the number of levels won in the run.
- A pass was 20 levels at first and was cut to 10, because a full pass felt too long. Levels 11–20 and
  their boss, the Overlord, are still in `levels.py` (`ALL_LEVELS`, `ALL_BOSS_LEVELS`), switched off
  by `LEVEL_COUNT = 10`. Raising `LEVEL_COUNT` brings them back.

## 2. Records: what each side plays against

Both kinds of records live in the permanent profile, not in the run, so a new run started on
either side has something to face.

Records are kept **per wave**: each level has five slots, one for each of its waves.

| Record | Written when | Contents of each wave slot | Used by |
|---|---|---|---|
| **Tower record** for level N | You clear Towers level N | The strongest comp you had during that wave: kinds, tiles, value | Monsters level N |
| **Monster record** for level N | You win Monsters level N | The wave you sent (queue order, hp multiplier, active buffs, value) plus its ability casts (time in the wave, position) | Towers level N |

- **Only a stronger record replaces the old one**, slot by slot. A comp, or a wave, replaces what's
  stored only if its value is higher (a tie keeps the old one). So one level's five slots can come
  from different clears, and the challenge never gets easier, across runs too.
- **"During wave w"** means from the end of wave w−1 to the end of wave w: the build phase before
  the wave, plus the wave itself. The peak in that window is found the same way as the level-wide
  `strongest_comp`: check just before every sell and when the window closes. The logs get
  `strongest_comp_by_wave` next to `strongest_comp`.
- **Value:** a comp's value is the gold put into its towers. A wave's value is the sum of its
  monsters' costs.
- Towers level N with no monster record (the first time ever, or levels a previous run never
  reached on the Monsters side) uses the generated waves. The same goes for a single missing
  wave slot.
- **Empty slots:** a wave sent with nothing in it (to save budget) has value 0 and isn't recorded,
  so the Towers side gets the generated wave there. A wave with no towers on the map isn't
  recorded either, so on the Monsters side the defender keeps the comp of the latest earlier wave
  (or has nothing, if no earlier wave had towers).
- The Monsters side only opens after Towers L10 has been beaten, so by then all 10 tower records
  exist.

## 3. Monsters side

### The defender
- **The defender grows wave by wave.** At the start of wave w, the map is set to the tower
  record's wave w comp. During the draft before wave w you see that comp, so you can plan against it.
- The towers don't move, sell or fuse during a wave.
- The defender has **20 lives for the whole pass**; they don't come back between levels. (This
  matches the Towers side, whose lives also last the pass.)
- **You clear a level** by taking at least 1 life within its 5 waves. The level always plays all 5
  waves, since extra lives taken carry forward. The panel shows the pace, e.g. "-3 here: clear
  (6 to go)".
- **You win the pass** the moment the last life goes, on any level. The pass ends there and you
  switch sides.
- **The finale:** the Towers pass after a won Monsters pass ends on the level and wave where the
  last life went, and **the Warden joins that wave** (on top of the recorded wave, with its hp
  multiplier and upgrades; a Warden already drafted into it isn't doubled). The banner says "FINAL
  LEVEL", the header reads "Level 3 of 3", and the wave counter counts to the finale wave. Clearing
  it wins that Towers pass. Winning the Monsters pass early makes the next Towers pass shorter, but
  it ends on the wave that just beat you, plus a boss. That punishes ending early without ruling it
  out, and it gives speedruns their own challenge. A win on the last wave of the last level is the
  full pass, with the Warden added to the record's last wave.
  - The finale belongs to the run (`finale` in the save). Monsters passes, and Towers passes that
    start a new run, have none.
- **You lose** (and the run ends) if a level takes no lives, or if the last level ends with lives
  left.
- There's no cap on how many lives one level can take (`max_lives_per_level: 0` in
  `monsters.json`). See section 9 for what that allows.

### Budget
- Each wave adds **the larger of** two amounts to the budget:
  - the **value of the original generated wave** for that level and wave (made with a seeded RNG,
    so it's the same every time), and
  - a **share of the defender's comp value** for that wave. The share starts at **40%** and grows
    with every Monsters level won in the run ("stealing" from the towers): +1%, +2% or +3% for a
    weak, normal or strong record (section 5). It resets with the run.
- **Pace bonus (catch-up):** at the start of each level the share goes up **3% for every life the
  run is behind** an even pace (2 lives per level: 0 expected at level 1, 10 by level 6), at most
  **+15%**. Being ahead doesn't lower it (`pace_min: 0`): when it did, a strong first level left
  too small a share to take a life on the next one, so a good start lost the run. The panel shows
  it, e.g. "claims 55% (+15% pace)".
- Every monster type gets a `cost`. For the existing types, cost = the old kill reward
  (basic 5, fast 6, tank 12, champion 80, bosses 400 / 1000). So "the army your towers beat" and "the
  gold your towers earned from it" are the same number.
- Unspent budget **carries over** to the next wave of the same level. You can starve early waves
  and save up for one big push.
- The rare **War Chest** unlock raises the budget (+15% per rank) on top of that. A bigger army is
  also worth more kill gold when your next Towers pass faces it, so the tower side earns more.
- The numbers (`share_start`, `pace_per_life`, `pace_max`, `pace_min`, `starter_picks`, and the
  reward tiers) are in `monsters.json`.
- Monster HP still scales with the level's and wave's hp multiplier, exactly as today.
- On boss levels the boss is in the last wave's draft. It costs its value, and if it gets through
  the defender loses every life it has left, which wins the pass.

### Stat upgrades
- Three upgrades are bought with the budget during the draft and **last for the rest of the pass**,
  applying to every monster sent: **Vitality** (+15% HP per rank), **Stride** (+10% speed per rank,
  capped at +50%) and **Plating** (+2 flat armor per rank, so it also armors monsters with none).
  Up to 5 ranks each.
- **Price:** rank r costs `upgrade_price` (25%) × r × the current level's budget (its five waves'
  budgets added up), so they stay expensive as budgets grow.
- Buying an upgrade sends nothing: the budget it costs is taken from the waves. (At first every
  purchase also sent Basics worth its price as an escort; that was dropped.)
- A rank bought in the current draft can be sold back (right click). Upgrades are saved with the
  run, and reset at the start of every Monsters pass.
- Keys `Q` `W` `E`, or click the buttons under the draft list.
### Draft phase (between waves)
- The panel lists your unlocked monster types with their cost.
- Click (or press `1`–`9`) to add one to the queue, and Shift to add 5.
- The queue shows on the map as a strip of icons in spawn order. Right-click an icon to remove it.
- Press `Space` to send the wave. Monsters spawn in queue order, each with its type's spawn gap.

### Watch phase (during a wave)
- Your unlocked **abilities** sit in the panel with cooldown bars, on keys `1`–`5`.
- Targeted abilities ask for a click on the map, and the others fire at once.
- Cooldowns count game time, so they speed up with the game.

## 4. Content (version 1)

All numbers will live in a new **`monsters.json`**, the monster-side counterpart of
`towers.json`: enemy types, buffs, abilities and the reward pool. The mechanics are written in
code, but you can rebalance without touching it. `ENEMY_TYPES` moves out of `levels.py` into this
file.

### New monster types (unlockable)
| Type | Mechanic | Counters | Countered by |
|---|---|---|---|
| **Swarmling** | Tiny and very cheap (cost 2, 8 HP), spawns fast | Single-target towers, overkill | Splash |
| **Armored** | Every hit loses a flat amount of damage | Rapid fire (Minigun, Flak) | Big hits (Sniper, Railgun) |
| **Healer** | Heals nearby monsters over time | Burn, slow attrition | Burst, focus fire |
| **Splitter** | Splits into 3 Swarmlings when it dies | Single big hits | Splash, chain |
| **Phantom** | Every 4 s it can't be targeted for 1.5 s | Long-range snipers | Area slows, splash |
| **Juggernaut** (rare) | 300 HP and immune to slows | Frost lines | Raw DPS |

### Buffs (passive, up to 3 ranks, apply to all your monsters)
| Buff | Per rank |
|---|---|
| Thick Hide | +10% HP |
| Swiftness | +6% speed |
| Insulation | −15% burn damage |
| Thaw | Slows are 15% weaker |
| War Chest (rare, 5 ranks) | +15% budget |

### Active abilities
| Ability | Target | Effect | Cooldown |
|---|---|---|---|
| **EMP** | Area, radius 90 | Towers in it stop firing for 3 s | 20 s |
| **Smokescreen** | Area, radius 100 | Towers in it lose 40% range for 6 s | 18 s |
| **Frenzy** | All monsters | +50% speed for 4 s | 25 s |
| **Mend** | All monsters | Heals 25% of max HP | 30 s |
| **Bulwark** | All monsters | −50% damage taken for 3 s | 30 s |

Extra ranks of an ability cut its cooldown by 15%.

On the Towers side, abilities from a monster record are **replayed** at their recorded time and
place. Each one is shown as a ring about 1 s before it lands, so you can see it coming.

## 5. Unlocks: pick 1 of 3 (or 2)

There are two pools, one per side. A win draws cards from **its own side's** pool, and picks are
**permanent**.

**What you beat sets what you get** (like Clash of Clans paying less loot for weaker bases). Every
level's record is rated against **par**, the value of the level's generated waves:

- **Monsters side:** the defender's strongest comp in the level ÷ par. On a real run's records this
  goes from 1.3× (level 1) through 2.2–3.1× (levels 2–4) to 4.0–4.6× (levels 5–7, the hardest).
- **Towers side:** the monster record's waves added up (generated waves where there's none) ÷ par,
  so playing generated waves is exactly 1×.

| Tier | Monsters side | Towers side | Cards offered | Share growth (Monsters wins) |
|---|---|---|---|---|
| Weak | under 2× | under 1× | 2 | +1% |
| Normal | 2× to 4× | 1× to 2.5× | 3 | +2% |
| Strong | 4× and up | 2.5× and up | 3, one of them a sure rare (while any are left) | +3% |

The card screen says which tier the win was and what it gave. Crushing a weak level 1 pays the
least, and the walls pay the most. The starter pack is always normal. The score (levels won) isn't
weighted by tier yet.

| Win on | Gives | Available |
|---|---|---|
| Monsters side | A monster card (types, buffs, abilities, War Chest) | Always |
| Towers side | A tower card (see below) | Only after Monsters L10 has been beaten once |

The first time you play the Monsters side, you get a **starter pack**: 3 pick-1-of-3 screens of
monster cards. After that, monster cards only come from Monsters wins. So Monsters level 1 must
stay winnable, or the side would be a dead end (see the balance findings).

- **Monster card weights:** type 3, buff rank 3, ability 2, War Chest 1 (rare, gold border).
- Maxed items leave the pool. If a pool is empty, the screen is skipped.

### Tower cards (first draft)
| Card | Per rank | Max |
|---|---|---|
| Sharpened Guns / Cannons / Frost | +8% damage for that line (finals count for both of their parent lines) | 3 |
| Long Barrels | +5% range for all towers | 3 |
| Treasury | +50 gold at the start of each Towers pass | 3 |
| Fortify | +2 lives at the start of each Towers pass | 3 |
| Salvage | +5% sell refund (70% → 85%) | 3 |
| Detector (rare) | Towers can target phased Phantoms | 1 |
| Piercing Rounds (rare) | Armor is halved | 1 |
| Grounding (rare) | EMP and Smokescreen last half as long | 1 |
| Hotter Fuel | +15% burn damage (answers Insulation) | 3 |

The rare tower cards are direct counters to monster unlocks, so each side's progress answers the
other's.

## 6. Saving

There are two files, both git-ignored:

| File | Lifetime | Contents |
|---|---|---|
| `user/profile.json` | Forever | Unlocks and ranks (both pools), per-wave tower and monster records, `monsters_side_unlocked`, `tower_cards_unlocked`, best run |
| `user/savegame.json` | One run | Side, pass, level, gold and lives (the defender's on the Monsters side), rebuild list (Towers side), stat upgrades (Monsters side), the finale (level, wave) a Towers pass ends on |

- The save becomes the **run in progress**. Continue on the start screen resumes it at the start
  of the current level.
- **Change from today:** after a game over the run is over, so the save is deleted and
  "C: continue after a game over" goes away. That's what makes losing mean something.
- **Known loophole, accepted for now:** quitting in the middle of a level and continuing restarts
  that level, so a losing level can be retried.
- Gold and lives reset to 150 / 20 at the start of every Towers pass.

## 7. Code structure

`main.py`'s `Game` is already about 700 lines, so each side's logic gets its own module:

| Module | Contents |
|---|---|
| `monsters.json`, `monsters.py` | Loader and checks for enemy types and abilities (like `towers.py`) |
| `unlocks.json` | Both card pools: each card's side, effect, numbers per rank, max rank, weight, rarity |
| `progress.py` | `Profile` (permanent), the run save, records, the reward pool and drawing cards |
| `entities.py` | New status effects: tower `disabled` / `range_mult`; enemy armor, heal aura, split, phase, damage and speed modifiers; buffs applied at spawn |
| `attack.py` | `AttackMixin`: placing the defender, draft queue, budget, abilities, the win / lose rule, recording the monster record |
| `main.py` | `Game` keeps the shared loop and the Towers side, picks the side per pass, runs passes and run flow |
| `graphics.py`, `attack_view.py` | Shared drawing / Monsters-side panel, queue strip, ability bar, card screen, run-over and side-pick screens |
| `balance_log.py` | Logs record `side` and `pass`. Monsters-side logs add the draft and ability events |
| `waves.json`, `waves.py` | Generated Towers-side waves and the scouts' counters (section 12) |
| `music.py`, `music.json` | The soundtrack. `plan(game)` says which cue should play, how intense and whether ducked; `Music` (built in `main()`, never in tests) fades toward that every frame in real time. Stems are decoded on a thread when a level loads |

## 8. Build plan

Each phase ends with the full test suite green, and you can play the game after every phase.

| # | Phase | Delivers | Tests |
|---|---|---|---|
| 0 | **Groundwork** | Comp tracking moves into `Game`, now per wave as well (the log copies both); `progress.py` with `Profile`; per-wave tower records written on every Towers clear, keep-strongest | Records match the log's comps; only stronger slots replace; profile round-trip, corrupt profile ignored |
| 1 | **Monster data and mechanics** | `monsters.json` + loader; the 6 new types, 5 buffs, 5 abilities as plain functions on entities; tower status effects. No UI yet | One test per mechanic (armor vs rapid fire, split, phase, heal, EMP, smoke…); broken-file errors |
| 2 | **Monsters side** | Defender from a record, draft UI, budget and carry-over, abilities during waves, win / lose, monster record saved | Clicks and keys drive a draft; win by draining lives; lose after wave 5; budget is deterministic |
| 3 | **Towers side vs records** | Waves come from monster records, abilities replayed with warning rings, kill gold = monster cost | Replay matches the record; fallback to generated waves |
| 4 | **Rewards** | `unlocks.json`, both pools; pick-1-of-3 screen after wins (tower cards gated until Monsters L10 is beaten); tower card effects | Seeded draws, maxed items leave the pool, the pick is saved, the gate works, each tower card's effect |
| 5 | **Run flow** | Passes, side switch after L10, run over, side pick (once unlocked), save v2, Continue | A full simulated loop T→M→T with bots; run over deletes the save and keeps the profile |
| 6 | **Balance and docs** | Bot experiments, the budget rule fixed (section 9), scripted-draft slow tests, README / TESTING / docstrings | Slow tests: Monsters L1 stays winnable; level 1 and 2 reward different plans |

Phases 0–1 change nothing you can see, apart from the records being written. Phase 2 is the
first one you can play on the Monsters side (reachable through a debug flag, `--monsters`, until
phase 5 wires up the run flow).

## 9. Balance findings

Measured with bots (the Towers bot from `tests/helpers.py` setting records for levels 1–8, and
scripted Monsters drafts against them).

**The original budget rule couldn't keep up.** The Towers side keeps its gold from level to level
and gets full refunds, so its records snowball. With the budget pegged to the generated waves:

| Level | Monster budget for the whole level | Defender's comp in wave 5 |
|---|---|---|
| 1 | 310 | 470 |
| 3 | 583 | 1,870 |
| 5 | 725 | 3,690 |

Bots with no unlocks won 1 level in 30; with 5 unlocks, about 3 in 5. A starter pack only helps
level 1. Stealing a fixed amount per win, whether as a one-time bank (even 100% of the defender's
comp) or as permanent per-wave income (up to 25%), still lost at level 2 every time. Towers are
refunded each level while monsters are used up, so only a budget that scales with the defender
keeps up.

**The share rule.** At a fixed 30% share: no unlocks mostly lost, 5 unlocks won 9 of 10. With the
starter pack, a 25–35% starting share still lost Monsters level 1 almost every time: its records
are small, so the share adds little over the wave values there. At **40%**, saving everything for
one push wins level 1 every time, and evenly paced waves still lose. That's the chosen start.

**Different levels reward different plans.** With no unlocks:

| | Save for one push | Pace evenly |
|---|---|---|
| Level 1 | wins | loses |
| Level 2 (record ends on Dragon + Frostbite) | loses: Frostbite slows the whole column, Dragon burns it | wins |

Juggernauts (immune to slows) beat that level 2 record outright. Both rows were pinned by slow tests,
until the early hp boost below: the bot's level 2 record now ends on Railgun + Blizzard (990 gold),
which falls to both plans.

**The early waves were too easy (2026-10-15).** A first playthrough held 1,250 gold by level 3: 3–6
towers cleared levels 1–2 without a leak, and income (about 500 gold of kills and 175 of wave bonuses
a level) piled up. A bot that only buys after a leak, starting from the Gun, ended level 3 with about
1,050 gold banked. Kill gold doesn't scale with hp, so generated waves now get +1.5 hp multiplier per
wave over the first 15 waves (`EARLY_HP`, `EARLY_WAVES` in `levels.py`; the late game keeps the
+22.5, about +20% at level 10). The same bot now banks 150–290 by level 3. It's deliberately harsh:

| Bot (seeds 0–5) | Before | After |
|---|---|---|
| Buys Gun, Cannon, Frost in turn | Clears levels 1–9 with 20 lives | Falls on levels 2–4 |
| Buys Guns only | | Falls on levels 3–7 |

Weaker comps have to be fixed by the player now. `+1.0` was the edge where the mixed bot still
reached level 10 (with 1–9 lives), and `+0.75` lost it few lives but left 600–1,000 gold banked by level
3. The Monsters side keeps the plain curve (`wave_hp_mult`) for its drafts, so a monster record
replayed on levels 1–3 is weaker than the generated wave it replaces.

**Level 1 smoothed (2026-10-20).** In the first playtest of the reworked waves, level 1 cost 9 lives and
levels 2–3 none. With the full boost from wave 2, the multiplier went 1 → 3.04 → 5.16 → 7.36 → 9.64. On level 1
the boost now ramps in (`d / WAVES_PER_LEVEL` of it): 1 → 1.84 → 3.36 → 5.56 → 8.44, then 12 on level 2 as
before, so no step is over ×1.85. The Gun-only bot now loses 0–3 lives on level 1 (was 5–9) and the mixed
bot 5 (was 13).

**Berserkers and Saboteurs in the later waves (2026-10-15).** The first playthrough's later levels were a
walkover for five adjacent Frost Lances, so generated waves swap Basics for Berserkers (10% of the wave
from level 4, 15% from 6, 20% from 8) and Saboteurs (1, then 2 in waves 4–5 from level 6; 2, then 3 from
level 8): `BERSERKERS` and `SABOTEURS` in `levels.py`. Levels 1–3 roll nothing extra and don't change.
(Replaced by the wave rework, section 12: Berserkers and Saboteurs are now newcomers of levels 4 and 6.)
Replaying that playthrough's own comps, wave by wave on the tiles they stood on (towers frozen, no
building between waves):

| Level | Lives lost before | After | Most towers knocked out at once |
|---|---|---|---|
| 4–5 | 0 | 0 | 0 |
| 6 | 0 | 6 | 1 |
| 7 | 10 | 20 | 5 |
| 8 | 0 | 12 | 6 |

Berserkers alone don't trouble Frost Lances (they rarely survive a hit long enough to sprint); the
Saboteurs, blacking out the stacked Lances, do. The replay can't spend the 2,000+ gold that run had banked
by level 6, so a real player spreading out and building more should lose much less. The swaps also raise
`wave_value`, so Monsters-side budgets on levels 4+ grow by about as much.

**Lives carried over (the current rule).** Against the tower records from a real run (levels
1–10, 410 to 5,920 gold), with lives lasting the pass and no cap per level:

| Strategy | Lives taken per level | Result |
|---|---|---|
| Splitter / Armored / Tank + Bulwark (the player's unlocks), even waves | 20 | Pass won on level 1 |
| No unlocks, save for wave 5 | 20 | Pass won on level 1 |
| No unlocks, even Basic / Fast / Tank | 0 | Run over on level 1 |
| No unlocks, Tanks only | 10, 8, 0 | Run over on level 3 |

Each level on its own: levels 1–3 and 8–10 fall easily, levels 4–6 (2,320 to 3,840 gold) hold
against most plans. A cap of 3 lives per level made the pass last until about level 7, and was
won only by bots that put the rest of each level's budget into upgrades once the cap was reached.
**No cap was chosen for now**: an early blowout ends the pass, forfeits the levels (score) and cards
it skipped, and leaves a record the Towers side has to beat. That record is all or nothing: the
Towers bot lost level 1 six times out of six to a Splitter/Armored push saved for wave 5, but held
easily against an even-paced record and a push without unlock types.

**Pace bonus and record tiers (current).** Same records, no cap:
- Level-1 blowouts still win the pass (nothing is expected by level 1, so the pace can't apply), but
  level 1's record is weak: 2 cards and +1% instead of 3 cards and +2%.
- A pace cut for being ahead (3% per life, up to 15%) made strong starts lose: "save for waves 3 and
  5" took 15 lives on level 1, then 0 on level 2 at a 26% share, so the run ended with 5 lives to go.
  Without the cut it wins the pass on level 2. Hence `pace_min: 0`.
- The bonus for being behind barely moves levels 4–7. Even +50% left most plans at 0 lives there,
  and levels 7 and 8 have the same 3,840-gold comp but only level 8 falls. Those defenses
  (Avalanche, Dragon and Tesla slowing, burning and chaining crowds) are beaten by counters, not by
  budget: the Splitter/Armored mix breaks levels 4, 5 and 7, and with upgrades level 6 too.

**The finale.** We won Monsters passes against the tower records of a real run, then had the Towers
bot play the shorter pass that followed, on 4 seeds, with the Warden and with a Basic in its place:

| Monsters pass won with | Finale | Bot wins with a Basic | Bot wins with the Warden |
|---|---|---|---|
| No unlocks, save for wave 5 | L1 w5 (67 monsters) | 4 / 4 | 4 / 4 |
| No unlocks, every upgrade | L3 w2 (+15% HP, +2 armor) | 4 / 4 | 3 / 4 |
| Unlocks, even waves | L1 w5 (15 monsters) | 4 / 4 | 4 / 4 |
| Unlocks, upgrades, save for wave 5 | L1 w5 (+30% HP, +2 armor) | 4 / 4 | 2 / 4 |
| Unlocks, save for wave 5 | L1 w5 (46 monsters) | 0 / 4 | 0 / 4 (the record alone already wins) |

The Warden makes the finale harder, most of all after upgrades (it gets them too), but it can be
beaten.

**Not yet known:** balance past level 2, and on Towers passes against real monster records. The
bots are crude (they don't counter-pick or aim abilities), and their tower records spend every
coin, so human records will be weaker. These need playtesting. The balance logs record everything
needed to tune from real games.

## 10. Known gaps

- Quitting mid-level and continuing restarts the level (accepted, see section 6).
- If you quit during the starter pack, it's offered again in full next time (on top of the picks
  already made).
- On the Monsters side the panel shows no stats for a selected tower, only its range on the map.
- With no cap on lives per level, a strong push can win the Monsters pass on level 1 (section 9). The
  finale (section 3) makes the next Towers pass end on that wave with the Warden added.
  A record the Towers side can't beat is kept forever, so it could block every later Towers pass at
  that level.

## 11. Tower unlocks

Status: **built** (2026-10-15), not yet playtested.

A new profile starts with **the Gun only**. Every other tower, in every tier, is unlocked for good
by an achievement or a discovery. The unlocks pace the fusion tree: each one should arrive just as
the player runs into the problem it solves, so the unlock also teaches the tower.

Only the Towers side has achievements, and only towers are unlocked. The Monsters side is
unchanged (its starter pack and monster cards stay), and its defender is a tower record, which
only ever holds towers the player owned.

### How unlocks happen

| Tiers | How | Why |
|---|---|---|
| 1–3 | **Achievements** that show the need for the tower, or reward mastering the one before | Teaching: the goal shows the problem the tower solves |
| 4, the first two | **Discovery**: fusing two tier 3 towers from different lines makes the tier 4 tower and unlocks it, for the first two tier 4 towers ever made | Rewards experimenting; the first finals feel found, not given |
| 4, the other ten | **Hard achievements**: long-term or skill feats (beat the game, hoard gold, kill the Warden fast) | Late goals for players who know the game |

- **Two paths for the early unlocks.** Each tier 1–3 achievement has a skill path *or* a slow
  path (e.g. "let a Fast through" or "kill 40 Fasts"), so a struggling player can't get stuck with
  the Gun only, losing the same level run after run.
- **Parents first.** A tower's achievement is hidden, and counts nothing, until the player owns
  every tower it's fused from (the one before it in its line, or a final's two tier 3 parents).
  Until then the tree shows "Unlock the X first", and the HUD only pins achievements that can be
  worked on. A tower unlocked by an event doesn't let its children count that same event.
- **Discovery** works on any recipe until two have been discovered. After that a locked recipe
  can't be fused: the drag preview shows the lock and the achievement it needs. Each tier 4 tower
  has its own achievement; one that was discovered just never needs it.
- **The tier 3 branch screen** shows a locked branch greyed out with its achievement. If both
  branches are locked, the two tier 2 towers can't be fused.

### When an unlock arrives

- Progress is counted live, during waves and between them.
- An unlock earned during a wave becomes usable at the **next build phase**. At the start of that
  build phase a **pop-up** shows each new tower (its picture, what it's good at, the achievement
  that earned it), in the style of the card screen. Several unlocks queue up, one card each.
- An unlock earned during the build phase (a discovery, or a goal about towers on the map) shows
  its pop-up at once and is usable straight away.
- In the build panel a new tower has a "NEW" badge until it's been placed once.

### Showing what's locked

- **The evolution tree (`T`)** shows locked towers as silhouettes, with the achievement and a
  progress bar ("Rifle: Cannons kill 10 monsters (4/10)"). Tier 4 towers not yet discovered show `???`
  and their two parents while discovery is still open.
- **The HUD** pins the closest unfinished achievement in a corner during the Towers side.

### Achievements (first draft; every number goes in the data file)

**Tiers 1–3**

| Unlocks | Achievement | Teaches |
|---|---|---|
| Cannon | Clear your first wave | Something new to build straight away |
| Rifle | Cannons kill 10 monsters | Use what you've unlocked |
| Frost | Let a Fast monster through, **or** kill 40 Fasts | Fast monsters need slowing |
| Mortar | Have 7 towers on the map at once | |
| Chiller | Have 2 Frosts on the map at once | |
| Minigun | One Rifle kills 60 monsters in a level | Rapid fire is about volume |
| Sniper | A Rifle lands the killing shot on a Tank or an Elite | Big hits are about precision |
| Bombard | One Mortar shot kills 4 monsters | Burst splash |
| Incinerator | Cannon-line towers, fusions included, kill 50 monsters (over all runs) | Spread damage over time |
| Blizzard | Keep 10 monsters slowed at once | Area control |

The first playtest of the reworked waves (2026-10-20) changed the first three: the Cannon now comes after
the first wave, the Rifle after 10 Cannon kills (it used to need 4 Guns, which came before any other tower),
and the Mortar after 7 towers of any kind (it was 3 Cannons).
| Shatter | Kill 30 slowed monsters in a level | Punishing slowed foes |

**Tier 4** (the two discovered ones skip theirs)

| Unlocks | Achievement |
|---|---|
| Solar Laser | Beat Towers level 10 for the first time |
| Railgun | Kill the Warden within 20 s of it spawning |
| Thermal Shock | Hold 1,000 gold at the end of the last wave of Towers level 10 |
| Avalanche | Win the finale Towers pass (after a Monsters pass) |
| Flak Battery | Kill 300 monsters in one level |
| Dragon | Burn towers (Incinerator, Thermal, Dragon) kill 500 monsters, by any damage (over all runs) |
| Hailstorm | Clear a level without losing a life, from level 5 on |
| Tesla Coil | Kill 25 monsters within 2 s |
| Frostbite | Clear a level where only Frost towers (fusions with a Frost parent included) deal damage |
| Frost Lance | Snipers or their tier 4 fusions (Railgun, Solar Laser, Frostbite, Frost Lance) kill 10 Elites (over all runs) |
| Glacier Breaker | Survive a wave with 60 or more monsters in it |
| Obsidian | Win 3 Towers passes |

Some of these need towers that may still be locked (Frostbite needs the Frost line to the
top, Dragon needs Incinerators). That's intended: the late goals build on the early unlocks.

### Effects on the rest of the game

- **Tower cards:** a card for a line with no unlocked tower (Sharpened Cannons before the Cannon)
  is left out of the pool.
- **Rebuild (`B`)** only rebuilds towers that are unlocked, which they always are, since unlocks
  are never lost.
- **Balance:** reaching the Monsters side (Towers level 10) takes longer while tier 4 towers are
  locked. That's welcome: the Towers side was too easy. The Monsters budget (section 9) stays as
  it is; balance gets revisited after playtesting.
- **Existing profiles:** see TODO.md. Until profile validation lands, a profile without
  `towers_unlocked` starts with the Gun only.
- **Peaks are sampled.** "Monsters in one tower's range" and "monsters slowed at once" are checked
  every 6 updates during a wave, not every update. "One Mortar kills 4 at once" counts the kills
  one tower made in a single update (burns left out), which is one shot.

### Code

| Piece | Change |
|---|---|
| `achievements.json` | Each achievement: id, name, condition type, target, scope (`level`, `wave`, `run`, `ever`), the tower it unlocks, and an optional second (slow) path. Checked at startup like `unlocks.json` |
| `progress.py` | `Profile.towers_unlocked`, `Profile.achievements` (id → progress for `ever` counters), `Profile.discoveries_left` (starts at 2) |
| New `achievements.py` | Loader, plus a tracker fed the same events `balance_log.py` gets (kills by tower kind, leaks by enemy kind, fusions, gold, wave and level ends), with per-level and per-wave counters it resets |
| `main.py` | The build panel and hotkeys only offer unlocked tier 1 towers; fusion and the branch screen check the result; pending unlocks pop up at the start of the build phase |
| `graphics.py` | The unlock pop-up, the NEW badge, the locked fusion preview, locked silhouettes and progress bars in the tree, the pinned HUD goal |
| `tests/` | A fixture that unlocks every tower for the existing bot and slow tests; one test per condition type; discovery stops after two; pop-up timing |

## 12. Wave rework: newcomers, packs and scouts

Status: **built** (2026-10-20), not yet playtested by a person. Rules in `waves.json`, code in `waves.py`.

The balance logs showed generated waves made of Basics, Fasts and Tanks only, with Berserkers from level 4 and
Saboteurs from level 6. Twelve of the seventeen monster kinds never reached the Towers side, and one strong
build of a single kind held from level 3 to level 8 without changing. The rework:

- **Each level brings in 1–2 monsters**, which stay for the rest of the pass. Where possible the newcomer is
  the problem a tower unlock solves (DESIGN section 11):

  | Level | New | Level | New |
  |---|---|---|---|
  | 1 | Fast, Swarmling (the Cannon's "15 in range") | 6 | Warded, Saboteur |
  | 2 | Tank, Armored (armor stops the Gun) | 7 | Thawling, Banner Bearer |
  | 3 | Splitter, Healer | 8 | (nothing new) |
  | 4 | Juggernaut, Berserker | 9–10 | (nothing new) |
  | 5 | Phantom, Mirage | | |

- **Levels 1–3 are scripted** wave by wave. From level 4 on, waves are generated. Each wave has a
  role (introduce, mix, pressure, counter, finale), made of slots filled from the level's newcomers, a pattern
  (escort, rush, swarm, wall, …) or the Basic/Fast/Tank stream.
- **Threat, not cost, sizes a generated wave.** Each monster's threat starts from `matchups.py`'s fair cost.
  The budget is 1.25 × (18 + 5.7 d), with d the wave's index in the pass, which is 1.25 × the old generator's
  average. Draft prices can change later without moving difficulty.
- **Packs** spawn with a 2 s pause between them (`Game.wave_pauses`; monster records have none).
- **The build panel previews the next wave** (or, during a wave, what's still to come), with a red line
  saying what the scouts countered.

### Scouts and counters

After each wave, `waves.scout` reports on the towers: the damage they dealt in that wave per tag
(single-target, light rapid fire, splash, slowing, burning, long range; by gold spent when nothing dealt any), whether 3+ stand within 60 px of one point on the path, and the
banked gold. The next generated wave changes when:

- **A tag dealt 40% of the damage.** A share of the wave becomes that tag's hardest roster monsters: 0% on
  levels 1–2, then 10% rising to 40% on levels 9–10. The share is weighted by role (half on the mix wave,
  ¾ on pressure, full on the counter and finale waves; never wave 1), plus 5% for every wave in a row the
  same tag stays on top, up to +20%. "Hardest" comes from `counters.scores`, exported by
  `uv run analytics/matchups.py --counter-scores`: Swarmling, Splitter and Fast against single-target;
  Elite, Banner Bearer and Fast against splash; Healer and Juggernaut against slowing; Elite against burning;
  Armored and Swarmling against light fire.
- **Towers are stacked by the path:** 1 Saboteur for 3 towers, 2 for more (from level 6).
- **Banked gold reaches 1.5× the towers' value:** one Looter per 1.5×, 3 at most, hidden in the middle of
  the wave's heaviest pack, not spammed (as decided). Looters are on the roster from the start but no pattern
  uses them, so they only ever come this way, from level 3 on.

Counters take the place of an equal threat from the back of the wave. That means single monsters from
streams and scripted packs, then whole repeats of patterns, never a newcomer and never a monster that
already counters the tag. A wave's threat stays the same. Records from the Monsters side get no counters
(they are the player's own counter), and `wave_value` uses the wave without counters.

**The scouts weigh damage, not gold (2026-10-20).** In the first playtest, level 3's main tag by gold was
splash (three Mortars, then Bombards: 48%), so the scouts sent Fast monsters, while one Frostbite
(32% of the gold) dealt 53% of the damage and froze the Fasts at a fifth of the path. Each tower now counts
the damage it dealt in the last wave (`Tower.wave_damage`, reset when a wave starts). The report says which
it used (`by`), and the hoard check still compares banked gold with the towers' value in gold.

### What changed from the proposal, and why

- **The Looter came in on level 8 in the proposal.** As a newcomer it filled a whole pack (15 Looters), the
  spam ruled out. It now joins the roster on level 1 and comes only as the hoard counter.
- **The counter lists come from data.** The proposal's lists (Mirage against single-target, Thawling and
  Warded against slowing, Phantom and Mirage against long range) didn't hold up against the full matchup
  tables. The scores are each tower's matchups against the median tower's, normalized by the tower's own
  average, so a tower that's weak everywhere only counts where it's weakest.
- **Only the tag on top picks the counters.** Weighting every tag by its share of the gold sounded better
  for mixed builds, but it diluted the counters into monsters those builds handle fine (see below).
- **Level 1 is lighter than the budget.** At the full budget, bots buying Guns lost level 1 on half the seeds
  and bots buying Gun, Cannon and Frost on every seed. The Swarmling burst (wave 4) and the extra packs of
  wave 5 did it. Level 1 now has 10 Basics, then 6 + 2 Fasts, 5 + 2 Fasts + 3, 3 + 10 Swarmlings, and
  6 + 2 Fasts + the Elite. Level 2 wave 2 has 3 Armored and 2 Fasts.

### Measurements

**Bots** (`tests/helpers.bot_play`, every tower unlocked, seeds 0–3), lives lost per level:

| Bot | Level 1 | Level 2 |
|---|---|---|
| Guns only | 5–9 (5 of them the Elite) | falls (one seed clears it with 13 lost, falls on 3) |
| Gun, Cannon, Frost | 13 | falls |
| Cannon, Gun | 8 | falls |

Before the rework, the Gun bot fell on level 2 as well and the mixed bot on levels 2–4. Bots never adapt, so
they can't say anything about counters.

**Replaying real comps.** The strongest comp of each wave in four logged playthroughs, frozen on its tiles,
was played against the old generator, the new waves without counters, and the new waves with counters. Lives
lost per level:

| Playthrough (main tag) | Level | Old | New | New + counters |
|---|---|---|---|---|
| 2026-10-11 21:37 (slowing: Avalanche, Breaker, Tesla, Lances) | 7 | 5 | 5 | 23 |
| | 8 | 5 | 19 | 51 |
| | 9 | 25 | 17 | 55 |
| 2026-10-11 20:29 (mixed; no tag on top, Saboteurs for stacking) | 5–9 together | 20 | 22 | 18 |

The replays have no tower cards, so they're far weaker than the real games (where the old waves cost
0 lives on these levels). Only the columns' differences mean anything, and only for comps that mostly hold.
The other two playthroughs, the Lance stack and the Minigun/Incinerator one, collapsed with or without
counters (90–190 lives a level). There, lives lost even drops with counters, because the Swarmlings that
replace Tanks take 1 life each instead of 2. The same replay with every tag weighted by its gold took the
slowing build's levels 7–9 to 0, 4 and 0 lives: the reason for the last change above.

### Not done / to watch

- **Playtest by a person.** The replays and bots can't tell whether a counter feels fair, or whether the
  preview gives enough warning.
- **Draft costs** (Juggernaut, Elite, Healer underpriced for the Monsters side) are for a later session with
  every monster stat on the table. Threat is separate, so that session won't move the Towers side.
- **Monster budgets moved** with the generated waves (`wave_value`): level 1's par went from 310 to 301 and
  wave 1 from 40 to 50. The 40% share rule (section 9) hasn't been rechecked with bots.
- **The slow playthrough tests** (`test_playthrough.py`) were already failing before the rework (they
  predate tower unlocks), so no long bot test covers the new waves yet.

## 13. Elites: one per level

Status: **built** (2026-10-21), not yet playtested by a person. Stats in `monsters.json` (`"elite": true`),
which level gets which in `waves.json` (`levels[i].elite`), pictures in `sprites.py`.

Every level without a boss used to end on the same Elite. Now six elites take turns, each with its own
answer, so the end of a level tests something different each time:

| Elite | HP | Speed | What it does | Answer | Levels |
|---|---|---|---|---|---|
| Champion | 400 | 30 | Nothing special: a big wall of HP | Any damage | 1 |
| Bastion | 320 | 26 | Armor 9: a Gun's 14 does 5 | Big hits (Rifle line, Cannon line) | 2, 7 |
| Hierophant | 300 | 30 | A ward that eats a whole hit every 3 s; calls a Healer every 12 s | Kill the Healers; rapid fire breaks the ward | 3 |
| Warlord | 340 | 28 | Up to twice as fast as it's hurt (enrage 1); slows can't push it below 50% | Burst it down before it runs; slows help less | 4, 9 |
| Wraith | 280 | 42 | Phases out of reach for 1.5 s every 4 s | Detector card, splash, a wide net of towers | 5, 8 |
| Plague Bloat | 240 | 26 | Bursts into 2 Splitters (6 Swarmlings) | Splash | 6 |

- Each one reuses mechanics the normal monsters already have, at elite scale, and each level's elite
  plays off what the level brings in (the Bastion with the Armored, the Hierophant with the Healer, the Warlord
  with the Berserker, the Wraith with the Phantom).
- All are worth 80 gold and take 5 lives, except the Bloat: 50 gold, as its brood pays out the rest.
- Only the Champion can be drafted on the Monsters side. The others are `draft: never`, so the draft
  panel (10 rows) doesn't grow.
- Achievements that name Elites (Big Game, Elite Hunter) count all six, and so does the music's danger
  layer.
- Tuned with `matchups.py --monsters champion,bastion,hierophant,warlord,wraith,bloat` (elites are allowed
  there). "Fair cost" at the mid checkpoint: Champion 83, Bastion 72, Hierophant 74, Warlord 99, Wraith 79,
  Bloat 74. At first the Hierophant scored 195: it called a Healer every 7 s and the Healers' auras stacked
  on it. The matchups play a stream of one kind, which flatters summoners and splitters, so the Bloat's 173
  at the early checkpoint says little: it comes on level 6.
