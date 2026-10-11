# Roguelike mode: design and plan

Status: **built** (phases 0–6, 2026-10-11). The open questions were settled along the way; see each
section, and [Balance findings](#9-balance-findings) for why the budget rule changed.

## 1. The loop

A **run** is a series of **passes**. A pass is all 20 levels played from one side.

```
Pass 1: Towers  L1 ... L20  ──beat L20──▶  Pass 2: Monsters  L1 ... L20  ──beat L20──▶  Pass 3: Towers ...
         │                                          │
         └──── lose any level ──▶  RUN OVER  ◀──────┘
                                       │
                                       ▼
                 New run: pick a side (only once Towers L20 has been beaten for the first time)
```

- **Towers side:** the game as it is today: build, fuse, survive 5 waves.
- **Monsters side:** the towers are your recorded comp for that level, and you draft the waves
  that have to break it.
- Each pass you clear sets the records the next pass plays against, so every pass faces your
  own previous best.
- Losing ends the run. Unlocks are kept forever.
- There's no final victory screen any more. Beating Monsters L20 sends you back to Towers L1, and a
  run goes on until you lose. Your score is the number of levels won in the run.

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
- The Monsters side only opens after Towers L20 has been beaten, so by then all 20 tower records
  exist.

## 3. Monsters side

### The defender
- **The defender grows wave by wave.** At the start of wave w, the map is set to the tower
  record's wave w comp. During the draft before wave w you see that comp, so you can plan against it.
- The towers don't move, sell or fuse during a wave. The defender has **20 lives**, reset every level.
- **You win** the level by draining all 20 lives within the 5 waves. **You lose** (and the run
  ends) if the defender survives wave 5.

### Budget
- Each wave adds **the larger of** two amounts to the budget:
  - the **value of the original generated wave** for that level and wave (made with a seeded RNG,
    so it's the same every time), and
  - a **share of the defender's comp value** for that wave. The share starts at **40%** and grows by
    **+2% for every Monsters level won in the run** ("stealing" from the towers). It resets with
    the run.
- Every monster type gets a `cost`. For the existing types, cost = the old kill reward
  (basic 5, fast 6, tank 12, elite 80, bosses 400 / 1000). So "the army your towers beat" and "the
  gold your towers earned from it" are the same number.
- Unspent budget **carries over** to the next wave of the same level. You can starve early waves
  and save up for one big push.
- The rare **War Chest** unlock raises the budget (+15% per rank) on top of that. A bigger army is
  also worth more kill gold when your next Towers pass faces it, so the tower side earns more.
- The three numbers (`share_start`, `share_per_win`, `starter_picks`) are in `monsters.json`.
- Monster HP still scales with the level's and wave's hp multiplier, exactly as today.
- On boss levels the boss is in the last wave's draft. It costs its value, and if it gets through
  the defender loses all 20 lives.

### Draft phase (between waves)
- The panel lists your unlocked monster types with their cost.
- Click (or press `1`–`9`) to add one to the queue, and Shift to add 5.
- The queue shows on the map as a strip of icons in spawn order. Right-click an icon to remove it.
- Press `Space` to send the wave. Monsters spawn in queue order, each with its type's spawn gap.

### Watch phase (during a wave)
- Your unlocked **abilities** sit in the panel with cooldown bars, on keys `Q` `W` `E` `R` `A`.
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
| **Armored** | Every hit loses a flat amount of damage | Rapid fire (Minigun, Dragon, Flak) | Big hits (Sniper, Railgun) |
| **Healer** | Heals nearby monsters over time | Burn, slow attrition | Burst, focus fire |
| **Splitter** | Splits into 3 Swarmlings when it dies | Single big hits | Splash, chain |
| **Phantom** | Every 4 s it can't be targeted for 1.5 s | Long-range snipers | Area slows, splash |
| **Juggernaut** (rare) | 300 HP and immune to slows | Frost lines | Raw DPS |

### Buffs (passive, up to 3 ranks, apply to all your monsters)
| Buff | Per rank |
|---|---|
| Thick Hide | +10% HP |
| Swiftness | +6% speed |
| Insulation | −20% burn damage |
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

## 5. Unlocks: pick 1 of 3

There are two pools, one per side. A win draws three cards from **its own side's** pool, and
picks are **permanent**.

| Win on | Gives | Available |
|---|---|---|
| Monsters side | A monster card (types, buffs, abilities, War Chest) | Always |
| Towers side | A tower card (see below) | Only after Monsters L20 has been beaten once |

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

The rare tower cards are direct counters to monster unlocks, so each side's progress answers the
other's.

## 6. Saving

There are two files, both git-ignored:

| File | Lifetime | Contents |
|---|---|---|
| `profile.json` | Forever | Unlocks and ranks (both pools), per-wave tower and monster records, `monsters_side_unlocked`, `tower_cards_unlocked`, best run |
| `savegame.json` | One run | Side, pass, level, gold and lives (Towers side), rebuild list, carried budget (Monsters side) |

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

## 8. Build plan

Each phase ends with the full test suite green, and you can play the game after every phase.

| # | Phase | Delivers | Tests |
|---|---|---|---|
| 0 | **Groundwork** | Comp tracking moves into `Game`, now per wave as well (the log copies both); `progress.py` with `Profile`; per-wave tower records written on every Towers clear, keep-strongest | Records match the log's comps; only stronger slots replace; profile round-trip, corrupt profile ignored |
| 1 | **Monster data and mechanics** | `monsters.json` + loader; the 6 new types, 5 buffs, 5 abilities as plain functions on entities; tower status effects. No UI yet | One test per mechanic (armor vs rapid fire, split, phase, heal, EMP, smoke…); broken-file errors |
| 2 | **Monsters side** | Defender from a record, draft UI, budget and carry-over, abilities during waves, win / lose, monster record saved | Clicks and keys drive a draft; win by draining lives; lose after wave 5; budget is deterministic |
| 3 | **Towers side vs records** | Waves come from monster records, abilities replayed with warning rings, kill gold = monster cost | Replay matches the record; fallback to generated waves |
| 4 | **Rewards** | `unlocks.json`, both pools; pick-1-of-3 screen after wins (tower cards gated until Monsters L20 is beaten); tower card effects | Seeded draws, maxed items leave the pool, the pick is saved, the gate works, each tower card's effect |
| 5 | **Run flow** | Passes, side switch after L20, run over, side pick (once unlocked), save v2, Continue | A full simulated loop T→M→T with bots; run over deletes the save and keeps the profile |
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
| Level 2 (record ends on Dragon + Absolute Zero) | loses: Zero slows the whole column, Dragon burns it | wins |

Juggernauts (immune to slows) beat that level 2 record outright. Both rows are pinned by slow tests.

**Not yet known:** balance past level 2, and on Towers passes against real monster records. The
bots are crude (they don't counter-pick or aim abilities), and their tower records spend every
coin, so human records will be weaker. These need playtesting. The balance logs record everything
needed to tune from real games.

## 10. Known gaps

- Quitting mid-level and continuing restarts the level (accepted, see section 6).
- If you quit during the starter pack, it's offered again in full next time (on top of the picks
  already made).
- On the Monsters side the panel shows no stats for a selected tower, only its range on the map.
