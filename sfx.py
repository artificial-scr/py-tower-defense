"""Sound effects: short one-shot sounds for what happens in the game (a tower firing, a monster dying,
a wave starting...). sfx.json lists them all, with what each should sound like; the files go in
assets/sfx as <name>.ogg (or .wav).

play(name) is fire and forget. A sound's `gap` (real-time seconds between two plays) and `max` (copies
at once) keep a fast game or a crowd from piling it up. With no mixer (no audio device), a missing
sfx.json or missing files, Sfx stays silent and the game plays on, so sounds can be added one at a time.
"""

import json
import os

import pygame

import music

HERE = os.path.dirname(os.path.abspath(__file__))
SFX_DIR = os.path.join(HERE, "assets", "sfx")
CONFIG_FILE = os.path.join(HERE, "sfx.json")
EXTENSIONS = (".ogg", ".wav")
VOLUMES = music.VOLUMES  # the Sound setting, in %, same steps as the Music one
DEFAULT_VOLUME = 75
CHANNELS = 16  # sounds at once, on top of the soundtrack's reserved channels
DEFAULT_MAX = 2
# Monster deaths by size (monsters.json `size`): up to SMALL, up to MEDIUM, larger; bosses have their own.
SMALL, MEDIUM = 11, 14


def load_config(path=CONFIG_FILE):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as err:
        print(f"No sound effects: {err}")
        return {"sounds": {}, "towers": {}}


CONFIG = load_config()


def fire_sound(kind, config=CONFIG):
    """The sound a tower kind makes when it fires, or None."""
    return config["towers"].get(kind)


def death_sound(spec):
    """The sound of a monster (its monsters.json spec) killed."""
    if "boss" in spec:
        return "boss_death"
    return "death_small" if spec["size"] <= SMALL else "death_medium" if spec["size"] <= MEDIUM else "death_large"


class Sfx:
    """The sound effects player. `volume` is the Sound setting (0-100). `clock` gives real time in seconds
    (for the gaps). Build one per launch, after the soundtrack (it plays on the channels the soundtrack
    doesn't reserve)."""

    def __init__(self, volume=DEFAULT_VOLUME, folder=SFX_DIR, config=CONFIG, clock=None):
        self.volume = volume
        self.config = config
        self.clock = clock or (lambda: pygame.time.get_ticks() / 1000)
        self.sounds = {}  # name -> pygame.mixer.Sound, for the files that exist
        self.last = {}  # name -> when it last played
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(music.FREQUENCY)
            pygame.mixer.set_num_channels(max(pygame.mixer.get_num_channels(), music.CHANNELS + CHANNELS))
            self.on = True
        except pygame.error as err:
            print(f"No sound effects: {err}")
            self.on = False
            return
        for name in config["sounds"]:
            path = next((p for p in (os.path.join(folder, name + ext) for ext in EXTENSIONS) if os.path.exists(p)),
                        None)
            if path:
                try:
                    self.sounds[name] = pygame.mixer.Sound(path)
                except pygame.error as err:
                    print(f"No sound for {name}: {err}")

    def play(self, name):
        """Play a sound from sfx.json, unless it's missing, muted, too soon after the last one or already
        sounding `max` times."""
        sound = self.sounds.get(name)
        if not self.on or not self.volume or sound is None:
            return
        spec = self.config["sounds"][name]
        now = self.clock()
        if name in self.last and now - self.last[name] < spec.get("gap", 0):
            return
        if sound.get_num_channels() >= spec.get("max", DEFAULT_MAX):
            return
        channel = pygame.mixer.find_channel()  # a free channel the soundtrack doesn't reserve
        if channel is None:
            return
        self.last[name] = now
        channel.set_volume(self.volume / 100 * spec.get("volume", 1.0))
        channel.play(sound)
