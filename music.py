"""The soundtrack: each level has a build cue (placing towers) and a wave cue (enemies on the map),
and a boss cue takes over when a boss walks in. A cue is 5 stems of one loop, all the same length,
layered by how threatening the map is: pads, bass, percussion, lead, danger.

The stems of a cue start together and loop forever; only their volumes change, so they never drift
apart. Switching cue starts the new one from its first bar while the old one fades out (build and wave
run at different tempos, so there's no shared bar line to wait for). plan() says what the game wants
to hear right now; Music.update() fades toward it every frame, in real time.

The cues' seeds are picked in music.json and copied into assets/music by tools/sync_music.py. With no
mixer (no audio device) or missing files, Music stays silent and the game plays on.
"""

import json
import os
import threading
from dataclasses import dataclass

import pygame

HERE = os.path.dirname(os.path.abspath(__file__))
MUSIC_DIR = os.path.join(HERE, "assets", "music")
CONFIG_FILE = os.path.join(HERE, "music.json")
FREQUENCY = 48000  # the stems' sample rate: the mixer runs at it, so nothing is resampled
STEMS = ("pads", "bass", "percussion", "lead", "danger")
VOLUMES = (0, 25, 50, 75, 100)  # the Music setting, in %
DEFAULT_VOLUME = 75

# Intensity (0-1) -> layers: each stem is at full volume from its FULL_AT, silent RAMP below it.
FULL_AT = (0.0, 0.25, 0.5, 0.75, 1.0)
RAMP = 0.2
BUILD = 0.75  # building and between levels: everything but danger
WAVE = 0.5  # a wave on its way: pads, bass, percussion
PRESSED = 0.75  # + lead: the front monster past PRESSED_AT of the path, or a crowd on the map
DANGER = 1.0  # + danger: a monster near the end, lives running low, or a boss / elite on the map
BOSS = PRESSED  # the boss cue never drops below the lead
PRESSED_AT, DANGER_AT = 0.5, 0.8  # share of the path the front monster has walked
CROWD = 12  # monsters on the map
LOW_LIVES = 0.25  # share of the level's starting lives

# Fades, in seconds
RISE, FALL = 1.0, 4.0  # a layer going fully up / down
FADE_IN = {"build": 2.0, "wave": 0.3, "boss": 1.0}  # the cue coming in
FADE_OUT = 2.0  # the cue going out (to silence too)
DUCK = 0.4  # volume under a pause or a panel over the map
DUCK_FADE = 0.3


@dataclass(frozen=True)
class Plan:
    """What should be heard: the cues the level needs loaded, the one playing (None: silence), how
    intense it is, and whether it's ducked under a pause or panel."""
    cues: frozenset
    cue: str | None
    intensity: float = 0.0
    duck: bool = False


def load_config(path=CONFIG_FILE):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as err:
        print(f"No music: {err}")
        return {"levels": {}, "boss": {}}


CONFIG = load_config()


def level_cues(theme_name, boss, config=CONFIG):
    """{"build", "wave"[, "boss"]} -> cue id ("<area>/<cue>") for a level; empty without music."""
    level = config["levels"].get(theme_name)
    if not level:
        return {}
    cues = {"build": f"{level['area']}/build", "wave": f"{level['area']}/wave"}
    if boss and config.get("boss"):
        cues["boss"] = f"{config['boss']['area']}/boss"
    return cues


def threat(game):
    """How intense a wave is: WAVE, PRESSED or DANGER, from where the monsters are and the lives left."""
    monsters = [e for e in game.enemies if not e.illusion]
    length = sum(a.distance_to(b) for a, b in zip(game.path_pts, game.path_pts[1:])) or 1
    front = max((e.travelled / length for e in monsters), default=0.0)
    if (front >= DANGER_AT or game.lives <= LOW_LIVES * game.lives_at_start
            or any("boss" in e.spec or e.kind == "elite" for e in monsters)):
        return DANGER
    if front >= PRESSED_AT or len(monsters) > CROWD:
        return PRESSED
    return WAVE


def plan(game, config=CONFIG):
    """What the game should sound like right now."""
    cues = level_cues(game.theme.name, game.level_boss is not None, config)
    overlay = game.overlay
    if overlay == "rewards":  # the cards after a win: the level just won, at full volume
        return Plan(frozenset(cues.values()), cues.get("build"), BUILD)
    if overlay in ("settings", "side_pick") or game.state not in ("build", "wave", "level_complete"):
        return Plan(frozenset(cues.values()), None)  # menus, run over, pass won: silence
    duck = game.paused or overlay is not None
    if game.state != "wave":
        return Plan(frozenset(cues.values()), cues.get("build"), BUILD, duck)
    intensity = threat(game)
    if "boss" in cues and any("boss" in e.spec for e in game.enemies):
        return Plan(frozenset(cues.values()), cues["boss"], max(BOSS, intensity), duck)
    return Plan(frozenset(cues.values()), cues.get("wave"), intensity, duck)


def layer_gains(intensity):
    """Each stem's volume (0-1) at an intensity."""
    return [min(1.0, max(0.0, 1 - (full - intensity) / RAMP)) for full in FULL_AT]


def toward(value, target, step):
    return min(target, value + step) if value < target else max(target, value - step)


class _Playing:
    """One cue sounding: its stems on their own channels, the cue's fade and each layer's volume."""

    def __init__(self, cue, sounds, channels, fade_in, intensity):
        self.cue, self.channels = cue, channels
        self.gain, self.fade_in, self.out = 0.0, fade_in, False
        self.layers = layer_gains(intensity)  # a cue starts with its layers where they belong
        for channel, sound in zip(channels, sounds):
            channel.set_volume(0.0)
            channel.play(sound, loops=-1)

    def step(self, dt, intensity, volume):
        """Move the fades on and set the channels' volumes; False once it has faded out."""
        if self.out:
            self.gain = max(0.0, self.gain - dt / FADE_OUT)
        else:
            self.gain = min(1.0, self.gain + dt / self.fade_in)
            self.layers = [toward(g, target, dt / (RISE if target > g else FALL))
                           for g, target in zip(self.layers, layer_gains(intensity))]
        for channel, layer in zip(self.channels, self.layers):
            channel.set_volume(volume * self.gain * layer)
        return self.gain > 0 or not self.out

    def stop(self):
        for channel in self.channels:
            channel.stop()


class Music:
    """The soundtrack player. `volume` is the Music setting (0-100). Build one per launch, then call
    update() every frame, paused or not."""

    SLOTS = 3  # cues sounding at once: the one playing and up to two fading out

    def __init__(self, volume=DEFAULT_VOLUME, folder=MUSIC_DIR):
        self.volume = volume
        self.folder = folder
        self.sounds = {}  # cue id -> its stems, decoded
        self.wanted = frozenset()  # the cues the level needs
        self.loading = None  # the thread decoding them
        self.playing = []  # _Playing, oldest first; only the last can be fading in
        self.duck = 1.0
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(FREQUENCY)
            pygame.mixer.set_num_channels(max(pygame.mixer.get_num_channels(), self.SLOTS * len(STEMS) + 8))
            pygame.mixer.set_reserved(self.SLOTS * len(STEMS))  # sound effects never take these
            self.free = [pygame.mixer.Channel(i) for i in range(self.SLOTS * len(STEMS))]
            self.on = True
        except pygame.error as err:
            print(f"No music: {err}")
            self.on = False

    # ---- loading --------------------------------------------------------------
    def prepare(self, cues):
        """Decode the level's cues in the background (a few seconds; the level banner covers it) and
        free the last level's, once they're silent."""
        if cues == self.wanted:
            return
        self.wanted = cues
        playing = {p.cue for p in self.playing}
        self.sounds = {cue: s for cue, s in self.sounds.items() if cue in cues or cue in playing}
        todo = [cue for cue in cues if cue not in self.sounds]
        if todo:
            self.loading = threading.Thread(target=self._load, args=(todo, cues), daemon=True)
            self.loading.start()

    def _load(self, cues, wanted):
        for cue in cues:
            paths = [os.path.join(self.folder, cue, f"{stem}.ogg") for stem in STEMS]
            try:
                sounds = [pygame.mixer.Sound(path) for path in paths]
            except (pygame.error, FileNotFoundError) as err:
                print(f"No music for {cue}: {err}")
                continue
            if self.wanted is wanted:  # not a level that's already been left
                self.sounds[cue] = sounds

    # ---- playing --------------------------------------------------------------
    @property
    def current(self):
        """The cue playing (not fading out), or None."""
        return self.playing[-1].cue if self.playing and not self.playing[-1].out else None

    def update(self, dt, plan):
        if not self.on:
            return
        self.prepare(plan.cues)
        if plan.cue != self.current and (plan.cue is None or plan.cue in self.sounds):
            if self.playing:
                self.playing[-1].out = True
            if plan.cue:
                self._start(plan.cue, plan.intensity)
        self.duck = toward(self.duck, DUCK if plan.duck else 1.0, dt / DUCK_FADE)
        volume = self.volume / 100 * self.duck
        for p in list(self.playing):
            if not p.step(dt, plan.intensity, volume):
                self._release(p)

    def _start(self, cue, intensity):
        if len(self.playing) == self.SLOTS:
            self._release(self.playing[0])  # the oldest is nearly silent by now
        channels, self.free = self.free[:len(STEMS)], self.free[len(STEMS):]
        fade = FADE_IN[cue.rsplit("/", 1)[1]]
        self.playing.append(_Playing(cue, self.sounds[cue], channels, fade, intensity))

    def _release(self, p):
        p.stop()
        self.playing.remove(p)
        self.free += p.channels
        if p.cue not in self.wanted:
            self.sounds.pop(p.cue, None)
