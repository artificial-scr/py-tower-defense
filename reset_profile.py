"""Reset the game to a new player: move profile.json and savegame.json aside as .bak files.

settings.json and logs/ are kept. Rename the .bak files back to restore the old profile.
Running it again overwrites the previous .bak files.
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    for name in ("profile.json", "savegame.json"):
        path = os.path.join(HERE, name)
        if os.path.exists(path):
            os.replace(path, path + ".bak")
            print(f"{name} -> {name}.bak")
        else:
            print(f"{name}: not found, skipped")


if __name__ == "__main__":
    main()
