# py-tower-defense

A tower defense game built with [pygame-ce](https://pyga.me/). You never upgrade a tower directly.
Instead, towers evolve by **fusing** two of them into a stronger one. There are 20 levels, each with
its own color theme and path, and boss fights on levels 10 and 20.

## Quick start

You need Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync              # create .venv and install pygame-ce (plus pytest for development)
uv run main.py       # play
```

The game opens on the settings screen, where you can choose a display scale. Press Enter to start.

| Option | Effect |
|---|---|
| `--no-log` | Don't write balance logs (see [Balance logs](#balance-logs)) |

## How to play

Enemies follow the path from one edge of the map to the other. Build towers on free tiles to stop
them. Each enemy that gets through costs you lives, and you lose when your lives run out.

- You start with **150 gold** and **20 lives**.
- Each level has **5 waves**. You start each wave yourself, so you can build as long as you like
  between waves.
- You earn gold for every kill, plus a bonus for clearing a wave (`20 + 5 × wave number`).
- Selling a tower gives back **70%** of everything spent on it, including the towers fused into it.
- When you move to the next level the map changes, so all your towers are **refunded at full
  price**. Press **B** (or the Rebuild button) to buy them all back in one go: same towers, same
  price, most expensive first, each on the free tile that covers the most path. You can drag them
  wherever you like afterwards.
- Enemies get tougher across the whole game, not just within a level. Waves grow longer and enemy
  HP goes up.

### Saving

The start of each level is a checkpoint, saved to `savegame.json` with your gold, lives and the
towers to rebuild. When you launch the game, or after a game over, press **C** to continue from
the start of the last level you reached. Winning the game deletes the save.

### Enemies

| Enemy | Traits |
|---|---|
| Basic | Average speed and HP |
| Fast | Quick and fragile, shows up from the 3rd wave |
| Tank | Slow and tough, costs 2 lives if it gets through |
| Elite | Arrives at the end of the last wave of every non-boss level, costs 5 lives |
| **The Warden** (level 10) | Boss: summons Fast minions and resists slows |
| **The Overlord** (level 20) | Final boss: summons Tanks and resists slows even more |

If a boss gets through, the game is over, no matter how many lives you have left.

## Fusion and evolution

Every tower starts as one of the three you can buy from the panel. To evolve a tower, drag it onto
a matching tower, or buy a tower and drop it straight onto one. The tower you drop onto stays where
it is, and the one you dropped is used up.

```
Tier 1   Gun ─────────┐   Cannon ──────────┐   Frost ──────────┐     (bought, 50 / 90 / 70 gold)
         2× same      ▼   2× same          ▼   2× same         ▼
Tier 2   Rifle            Mortar               Chiller
         2× same, pick one branch:
Tier 3   Minigun|Sniper   Bombard|Incinerator  Blizzard|Shatter
         two tier 3 towers from DIFFERENT lines:
Tier 4   12 cross-type towers (see below)
```

| Tier 4 tower | Fused from | Specialty |
|---|---|---|
| Flak Battery | Minigun + Bombard | 3 explosive shots at once |
| Dragon | Minigun + Incinerator | Rapid burning bursts |
| Railgun | Sniper + Bombard | Instant, huge, explosive |
| Solar Lance | Sniper + Incinerator | Instant beam, heavy burn |
| Hailstorm | Minigun + Blizzard | 4 slowing shots at once |
| Tesla Coil | Minigun + Shatter | Lightning that chains through 6 foes |
| Absolute Zero | Sniper + Blizzard | Instant freezing blast |
| Frost Lance | Sniper + Shatter | Slows, then deals 3× damage to slowed foes |
| Avalanche | Bombard + Blizzard | Giant slowing splash |
| Glacier Breaker | Bombard + Shatter | Splash, 2.5× damage vs slowed |
| Thermal Shock | Incinerator + Blizzard | Burns and slows an area |
| Obsidian | Incinerator + Shatter | Burn, slow, 2× damage vs slowed |

Press **T** in game to see the whole tree. While you drag a tower over another one, the game shows
what the fusion would produce.

## Controls

| Input | Action |
|---|---|
| `1` / `2` / `3` | Pick a tower to build (Gun, Cannon, Frost) |
| Left click | Place the picked tower / select an existing tower |
| Drag a tower | Move it to any free tile, even during a wave. Drop it on a matching tower to fuse them |
| Right click / `Esc` | Cancel placement / deselect |
| `Esc` (nothing selected) | Ask to quit. Press `Esc` again to quit |
| `S` | Sell the selected tower |
| `B` | Rebuild the previous level's towers |
| `C` | Continue from the last checkpoint (on the start screen or after a game over) |
| `T` | Show the evolution tree |
| `Space` | Start the next wave / continue to the next level (sending a wave is blocked for 1 s after a level change, so a double press can't start one on an empty map) |
| `F` / `Shift+F` | Change game speed: 1×, 2×, 4×, 10× |
| `P` | Pause |
| `O` | Settings (display scale, from 75% to 200%) |
| `R` | Restart after a game over or a win |

When a fusion has two possible results, press `1` / `2` or click a card to pick one.

## Modding towers

Tower stats and evolution are data, not code. Both files are read at startup:

- **`towers.json`**: each tower's stats (`range`, `damage`, `rate`, `proj_speed`, `cost` for tier 1
  towers) and its look (layered shapes and barrels). Optional mechanics are `splash`, `slow` +
  `slow_time`, `burn` + `burn_time`, `chain`, `multishot`, `instant` and `vs_slowed`.
- **`evolution.json`**: the three tier 1 → 3 lines and the twelve tier 4 recipes.

That means you can rebalance towers or add new ones without touching the Python code. If one of
the files is broken, the game stops with an error message that says what's wrong.

Levels, enemies and wave generation are in `levels.py`.

## Balance logs

Each level you play writes a JSON log to `logs/<session>/`, for example
`run01_level03_tundra_cleared.json`. A log records:

- damage, DPS, overkill and kills per tower and per tower kind
- spawns, kills, leaks and damage taken per enemy kind
- the economy and a wave-by-wave summary
- the level's strongest composition: the most valuable set of towers you had on the map at once
  (value = gold put into them), when you had it, and which towers were in it
- every buy, fusion, branch choice, move and sell
- a snapshot of the tower and enemy stats that were in effect

These logs are meant for tuning `towers.json`. Pass `--no-log` to turn them off. See
`balance_log.py` for the full format.

## Project layout

| File | Contents |
|---|---|
| `main.py` | The `Game` state machine (waves, fusing, input, logging hooks) and `main()` |
| `towers.py` | Loads and validates `towers.json` and `evolution.json` |
| `levels.py` | Level themes and paths, enemy types, wave generation |
| `entities.py` | `Enemy`, `Projectile`, `Tower`: the combat rules |
| `graphics.py` | Everything drawn on screen, plus display scaling |
| `balance_log.py` | Per-level balance logs |
| `tests/` | The pytest suite |

Your display scale is saved in `settings.json` and your progress in `savegame.json`. Both files
and `logs/` are git-ignored.

## Testing

```bash
uv run pytest                 # full suite (~40 s)
uv run pytest -m "not slow"   # skip the long bot playthroughs
```

The tests run headless, so they need no display. See [TESTING.md](TESTING.md) for what they cover,
the fixtures, and how to update the pixel snapshots.
