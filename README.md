# py-tower-defense

A roguelike tower defense game built with [pygame-ce](https://pyga.me/). You never upgrade a tower
directly. Instead, towers evolve by **fusing** two of them into a stronger one. There are 10 levels,
each with its own color theme and path, and a boss fight on level 10.

Beat all 10 levels and the game flips: you play the **monsters** against your own best tower
defenses, level by level. Beat those, and you defend against your own monster waves. A run goes on,
switching sides every 10 levels, until you lose a level.

## Quick start

You need Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync              # create .venv and install pygame-ce (plus pytest for development)
uv run main.py       # play
```

The game opens in a window at 200% (2040 x 1280, or as large as fits on a smaller screen), on the
settings screen, where you can switch to fullscreen, turn the ambient effects (drifting particles,
glowing maps) on or off, and set the music and sound effects volumes. Press Enter to start.

| Option | Effect |
|---|---|
| `--no-log` | Don't write balance logs (see [Balance logs](#balance-logs)) |
| `--no-music` | No soundtrack (see [Music](#music)) |
| `--no-sound` | No sound effects (see [Sound effects](#sound-effects)) |
| `--monsters` | Debug shortcut: start straight on the Monsters side |

## The run

```
Pass 1: Towers  L1 ... L10  ──beat L10──▶  Pass 2: Monsters  L1 ... L10  ──beat L10──▶  Pass 3: Towers ...
         │                                          │
         └──── lose any level ──▶  RUN OVER  ◀──────┘
```

- **Losing a level ends the run.** Your score is the number of levels won. The best run is kept.
- **Records:** every level you win becomes a record the other side plays against next time. Clearing
  a Towers level records the strongest set of towers you had during each of its 5 waves. Winning a
  Monsters level records the waves you sent, including where and when you used abilities. A record
  only ever gets replaced by a stronger one, so the challenge never gets easier.
- **Unlocks:** after a win, pick one of three cards (two after beating a weak record; a strong one
  guarantees a rare). They're permanent and survive the end of a run.
  Monsters wins give monster cards. Towers wins give tower cards once you've beaten Monsters level 10.
- **New run:** once you've beaten Towers level 10, every new run lets you pick which side to start on.

The full design, and the reasoning behind each rule, is in [DESIGN.md](DESIGN.md).

## The Towers side

Enemies follow the path from one edge of the map to the other. Build towers on free tiles to stop
them. Each enemy that gets through costs you lives, and you lose when your lives run out.

- You start each Towers pass with **150 gold** and **20 lives** (more with the Treasury and Fortify
  cards).
- Each level has **5 waves**. You start each wave yourself, so you can build as long as you like
  between waves.
- You earn each monster's cost in gold when you kill it, plus a bonus for clearing a wave
  (`20 + 5 × wave number`).
- Selling a tower gives back **70%** of everything spent on it, including the towers fused into it.
- When you move to the next level the map changes, so all your towers are **refunded at full
  price**. Press **B** (or the Rebuild button) to buy them all back in one go: same towers, same
  price, most expensive first, each on the free tile that covers the most path. You can drag them
  wherever you like afterwards.
- Waves come from your **monster record** for that level when one exists, abilities included. A
  pulsing circle warns you a second before an area ability lands. Without a record, the game
  generates the wave, and those get tougher across the whole game.

## The Monsters side

The towers on the map are your **tower record** for the level, and you have to get through them.

- **The defender grows wave by wave:** before each wave you see the comp it had during that wave
  in your record. Click a tower to see its range.
- **Draft** each wave between waves. Click a monster in the panel (or press its number) to add it
  to the queue, and hold Shift to add 5. The queue shows along the bottom of the map, and clicking an
  icon removes it. Then press Space to send the wave.
- **Budget:** each wave adds the larger of what the generated wave was worth and a **share of the
  defender's comp value**. The share starts at 40% and grows with every Monsters level you win in
  the run: +1%, +2% or +3% depending on how strong the defense was (weak, normal or strong compared
  with the level's generated waves). If the run is behind a pace of 2 lives per level, each level's
  share gets +3% per life behind (up to +15%). Unspent budget carries over to the next wave, so you
  can save up for one big push, or pace your waves. Different levels reward different plans.
- **Stat upgrades:** Vitality (+15% HP), Stride (+10% speed, up to +50%) and Plating (+2 armor), up
  to 5 ranks each, bought during the draft with `Q` `W` `E` or the buttons under the draft list.
  They last for the rest of the pass. They're expensive (a quarter of the level's budget times the
  rank), but each one also sends Basics worth its price as an escort (at most 60 per wave). Right
  click an upgrade to undo a rank bought in this draft.
- **Abilities:** during a wave, press their number (or click them) once they're ready. Area
  abilities then need a click on the map.
- **Lives last the whole pass:** the defender has 20 lives for all 10 levels. Take at least one in
  a level to clear it. Take the last one, on any level, and you win the pass. If a level takes no
  lives, or the last level ends with lives left, the run is over.
- **The finale:** the Towers pass after a Monsters win ends on the wave where the last life went,
  and the Warden joins that wave. Winning early means a shorter Towers pass that ends on that wave,
  with the Warden joining it.
- **Starter pack:** the first time you play the Monsters side, you pick 3 cards to begin with.

## Monsters

| Monster | Traits | Unlock |
|---|---|---|
| Basic | Average speed and HP | Always |
| Fast | Quick, with a Basic's HP | Always |
| Tank | Slow and tough, costs 2 lives if it gets through | Always |
| Elite | Very tough, costs 5 lives | Always |
| Swarmling | Tiny, cheap, fast; comes in crowds | Card |
| Armored | Blocks a flat part of every hit (not burns): shrugs off rapid fire | Card |
| Healer | Heals the monsters around it | Card |
| Splitter | Breaks into 3 Swarmlings when killed | Card |
| Phantom | Every 4 s it can't be targeted for 1.5 s (splash still hits it) | Card |
| Juggernaut | Huge and immune to slows | Rare card |
| Warded | A ward absorbs one whole hit (slow and burn included), then recharges for 2.5 s | Card |
| Mirage | Every 2.5 s, casts an illusion of itself ahead on the path: one hit pops it, it's worth nothing | Card |
| Berserker | Gets faster as it's hurt, up to twice as fast near death | Card |
| Thawling | Sprints +80% for 2 s whenever a slow wears off | Card |
| Saboteur | When killed, towers within 1.5 tiles stop firing for 2 s | Card |
| Looter | Takes no lives: steals 15% of the tower player's gold, or brings back 2× its cost as budget | Card |
| Banner Bearer | Monsters around it move 30% faster | Card |
| **The Warden** | Boss of level 10: summons Fast monsters and resists slows | Boss level, last wave; a Towers pass's finale wave |
| **The Brood Mother** | Boss: every 2.5 s shoots out 3 Spiderlings (1 behind, 2 in front); resists slows | No level yet |

If a boss gets through, its side loses every life at once.

### Abilities and buffs

| Ability | Effect | Cooldown |
|---|---|---|
| EMP | Towers in an area stop firing for 3 s | 20 s |
| Smokescreen | Towers in an area lose 40% range for 6 s | 18 s |
| Frenzy | All monsters +50% speed for 4 s | 25 s |
| Mend | Heals every monster by 25% | 30 s |
| Bulwark | Monsters take 50% less damage for 3 s | 30 s |

Extra ranks of an ability cut its cooldown by 15%. The buff cards (up to 3 ranks each) are Thick
Hide (+10% HP), Swiftness (+6% speed), Insulation (−20% burn damage) and Thaw (slows 15% weaker).
The rare War Chest card (up to 5 ranks) adds 15% to the draft budget.

### Tower cards

Sharpened Guns / Cannons / Frost (+8% damage for that line, and finals count for both parent
lines), Long Barrels (+5% range), Treasury (+50 starting gold), Fortify (+2 starting lives) and
Salvage (+5% sell refund) go up to 3 ranks. The rare cards counter monster unlocks: Detector
(target phased Phantoms), Piercing Rounds (halves armor) and Grounding (EMP and Smokescreen last
half as long). A tower record keeps the cards it was won with.

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

### Unlocking towers

A new profile owns only the **Gun**. Every other tower is unlocked for good by an achievement on the
Towers side, for example "Have 3 Guns on the map at once" for the Rifle, or "Have 15 monsters inside
one tower's range at once" for the Cannon. The first two tier 4 towers you ever make are unlocked by
fusing them: a **discovery**. The other ten need harder achievements, like winning a Towers pass,
holding 1,000 gold at the end of one, or killing the Warden within 20 s.

- A tower's achievement only shows, and only counts, once you own the towers it's fused from
  (the Sniper's once you have the Rifle, a final's once you have both its tier 3 parents).
- A locked tower can't be bought, and a fusion into it is refused. A locked tier 3 branch shows on
  the branch screen, but can't be picked.
- The evolution tree (**T**) shows each locked tower's progress. Point at one to see how to unlock it.
  The panel pins the locked tower closest to unlocking.
- A tower unlocked during a wave is announced, and can be used, at the start of the next build phase.
  One unlocked while building is announced at once. Any key or click puts the card away.
- Tower cards for a line you can't build yet (Sharpened Cannons before the Cannon) aren't offered.

## Controls

| Input | Towers side | Monsters side |
|---|---|---|
| `1`–`9`, `0` | `1`–`3`: pick a tower to build | Draft phase: draft that monster (`Shift`: 5 of them). During a wave: use that ability |
| Left click | Place the picked tower / select a tower | Draft from the panel, remove a queued monster, cast an aimed ability, see a tower's range |
| Drag a tower | Move it to any free tile, even during a wave. Drop it on a matching tower to fuse them | — |
| Right click / `Esc` | Cancel placement / deselect | Cancel aiming |
| `Backspace` | — | Take the last monster off the queue |
| `Q` / `W` / `E` | — | Draft phase: buy a rank of Vitality / Stride / Plating (right click its button to undo) |
| `S` / `B` | Sell the selected tower / rebuild the previous level's towers | — |

Both sides:

| Input | Action |
|---|---|
| `Space` | Send the next wave / continue to the next level / switch sides when a pass is won (sending a wave is blocked for 1 s after a level change, so a double press can't start one by accident) |
| `C` | Continue the saved run (on the start screen) |
| `T` | Show the evolution tree |
| `F` / `Shift+F` | Change game speed during waves: 1×, 2×, 4×, 10× (building always runs at 1×) |
| `P` | Pause |
| `O` | Settings (fullscreen, ambient effects on or off with `A`, music and sound volumes) |
| `F11` | Fullscreen on or off (the game is scaled up to fill the screen) |
| `M` | Music volume: 25%, 50%, 75%, 100%, off (anywhere, settings screen included) |
| `N` | Sound effects volume: 25%, 50%, 75%, 100%, off (anywhere, settings screen included) |
| `R` | Start a new run after the run is over |
| `Esc` (nothing to cancel) | Ask to quit. Press `Esc` again to quit |

On a choice screen (fusion branch, unlock cards, side for a new run), press the number on a card or
click it.

## Saving

There are two files, both git-ignored:

- **`profile.json`** is kept forever: your unlocks, the towers you own and your progress toward
  the others, the records for every level and wave, your milestones and your best run.
- **`savegame.json`** is the run in progress, saved at the start of every level (on the Monsters side
  with the defender's lives, your upgrades and any escort still to send). On the start screen,
  press **C** to continue it from the start of that level. Losing a level ends the run and deletes it.

## Modding

Stats and rules are data, not code. Every file is read and checked at startup, and if one is broken
the game stops with a message that says what's wrong.

- **`towers.json`**: each tower's stats (`range`, `damage`, `rate`, `proj_speed`, `cost` for tier 1
  towers) and its look (layered shapes and barrels). Optional mechanics are `splash`, `slow` +
  `slow_time`, `burn` + `burn_time`, `chain`, `multishot`, `instant` and `vs_slowed`.
- **`evolution.json`**: the three tier 1 → 3 lines and the twelve tier 4 recipes.
- **`monsters.json`**: every monster's stats, cost, look and mechanics (`armor`, `heal_aura`, `split`,
  `phase`, `slow_floor`, `summon`), the abilities, the stat upgrades, and the Monsters-side rules
  (`share_start`, `starter_picks`, `upgrade_price`, `escort_per_wave`, `max_lives_per_level`,
  `pace_per_life`, `pace_max`, `pace_min`) and the reward tiers (`rewards`).
- **`unlocks.json`**: both card pools, with each card's effect, numbers per rank, max rank, weight and
  rarity.
- **`achievements.json`**: the towers a new profile starts with, how many tier 4 towers can be
  discovered by fusing, and the achievement that unlocks each other tower (its goals, their
  conditions and targets).

Levels and wave generation are in `levels.py`. It holds 20 levels, but only the first `LEVEL_COUNT`
(10) are played; levels 11–20 and their boss, the Overlord, are kept as a backup.

## Balance logs

Each level you play writes a JSON log to `logs/<session>/`, for example
`run01_level03_tundra_cleared.json` (or `run01_monsters_level03_...` on the Monsters side). A log
records:

- damage, DPS, overkill and kills per tower and per tower kind
- spawns, kills, leaks and damage taken per enemy kind
- the economy and a wave-by-wave summary
- the strongest composition you had on the map, for the whole level and for each wave (value =
  gold put into the towers)
- every buy, fusion, branch choice, move, sell, ability and unlock pick
- a snapshot of the tower and enemy stats that were in effect

These logs are meant for tuning the data files. Pass `--no-log` to turn them off. See
`balance_log.py` for the full format.

## Project layout

| File | Contents |
|---|---|
| `main.py` | The `Game` state machine (waves, fusing, runs and passes, rewards, input, logging hooks) and `main()` |
| `attack.py` | The Monsters side: the defender from a record, drafting, abilities, winning and losing |
| `progress.py` | The permanent profile (records, unlocks, owned towers, milestones) and the card pools |
| `achievements.py` | Loads and validates `achievements.json`; the tracker that counts achievements and unlocks towers |
| `towers.py` | Loads and validates `towers.json` and `evolution.json` |
| `monsters.py` | Loads and validates `monsters.json` |
| `levels.py` | Level themes and paths, wave generation and wave values |
| `entities.py` | `Enemy`, `Projectile`, `Tower`: the combat rules, monster mechanics and abilities |
| `graphics.py` | Everything drawn on screen (shadows, animation, panels and overlays), plus display scaling |
| `effects.py` | Short-lived visual effects: rings, beams, explosions, sparks, shards, cast warnings, floating text |
| `sprites.py` | The tower and enemy pictures, drawn in code once per display scale (shaded, anti-aliased, one per direction); each enemy type's creature design and animation |
| `terrain.py` | The level maps, drawn once per level: textured ground, a path styled for each theme, shaded props |
| `ambience.py` | What moves on the map without affecting the game: particles for each theme, glowing cracks and crystals that pulse, the spawn portal and exit gate |
| `attack_view.py` | Drawing for the Monsters side |
| `unlock_view.py` | Drawing for tower unlocks: the unlock card, the pinned next unlock, locks over towers |
| `balance_log.py` | Per-level balance logs |
| `music.py`, `music.json` | The soundtrack: which seed each level plays, and the player that layers its stems |
| `sfx.py`, `sfx.json` | The sound effects: every sound the game needs, and the player that plays them |
| `assets/fonts/` | The game font, Orbitron (Medium and Bold), and its license |
| `assets/music/` | The soundtrack stems, `<area>/<cue>/<stem>.ogg` |
| `assets/sfx/` | The sound effects, `<name>.ogg` or `<name>.wav` (names from `sfx.json`) |
| `tests/` | The pytest suite |
| `tools/select_tests.py` | Picks the tests that cover what changed (see [TESTING.md](TESTING.md)) |

Fullscreen, the ambient effects and the music and sound volumes are saved in `settings.json`. That file,
`profile.json`, `savegame.json` and `logs/` are git-ignored.

## Music

Each level has two cues, generated by the separate soundtrack-maker project: a calm **build** cue while
you place towers and an intense **wave** cue while monsters attack. The Warden brings in a **boss** cue.
A cue is five stems of one loop (pads, bass, percussion, lead, danger) that always play together; the
game only changes their volumes, so the music follows the action without restarting:

| What's on the map | Layers |
|---|---|
| Building, and the screens between levels | pads, bass, percussion, lead |
| A wave starting | pads, bass, percussion |
| The front monster past half the path, or more than 12 monsters | + lead |
| A monster in the last 20% of the path, lives under 25%, or a boss / elite | + danger |

Switching between build and wave crossfades, with the new cue starting from its first bar. The music
is quieter under a pause or a panel (tree, choices, quit prompt) and silent on the settings, side-pick,
run-over and pass-won screens. The thresholds and fade times are constants at the top of `music.py`.

`music.json` picks a seed per level and cue. To change one, edit it and copy the stems in again with
`uv run tools/sync_music.py [path to soundtrack-maker/stems]` (a local script, kept out of git).

## Sound effects

`sfx.json` lists every sound effect the game needs, grouped (towers, hits, monsters, bosses, abilities,
building, draft, progress, ui), each with a description of what it should sound like. The `core`
ones are the set to make first. The game plays a sound when its file is in `assets/sfx` as
`<name>.ogg` (or `.wav`) and stays silent for the others, so sounds can be added one at a time.

Each tower plays the firing sound `towers` gives it, and a killed monster plays a small, medium or
large death by its size. A sound's `gap` (real-time seconds between two plays) and `max` (copies at
once) stop a fast game or a crowd from piling it up, and its `volume` is multiplied by the Sound
setting. Sounds marked `"hooked": false` are listed but not played yet: they need hooks inside
`entities.py` (hits, burns, wards...) or the views (button clicks).

The sounds are generated by the soundtrack-maker project, four seeds each. A sound uses seed 1 unless
its `sfx.json` entry has a `seed`. To change one, edit it and copy the sounds in again with
`uv run tools/sync_sfx.py [path to soundtrack-maker/sounds]` (a local script, kept out of git).

## Credits

The font is [Orbitron](https://fonts.google.com/specimen/Orbitron) by Matt McInerney, under the SIL Open
Font License 1.1 (`assets/fonts/OFL.txt`), using the Medium and Bold files from
[theleagueof/orbitron](https://github.com/theleagueof/orbitron). The music is generated by the
soundtrack-maker project. Everything else is drawn in code.

## Testing

```bash
uv run pytest                 # full suite (~55 s)
uv run pytest -m "not slow"   # skip the long bot playthroughs
uv run tools/select_tests.py --run   # only the tests that cover what changed
```

The tests run headless, so they need no display. See [TESTING.md](TESTING.md) for what they cover,
the fixtures, and how to update the pixel snapshots.
