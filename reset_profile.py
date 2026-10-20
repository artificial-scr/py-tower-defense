"""Reset the game to a new player: move user/profile.json and user/savegame.json aside as .bak files.

user/settings.json and logs/ are kept. Rename the .bak files back to restore the old profile.
Running it again overwrites the previous .bak files.
"""

import os

USER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user")


def main():
    for name in ("profile.json", "savegame.json"):
        path = os.path.join(USER_DIR, name)
        if os.path.exists(path):
            os.replace(path, path + ".bak")
            print(f"{name} -> {name}.bak")
        else:
            print(f"{name}: not found, skipped")


if __name__ == "__main__":
    main()
