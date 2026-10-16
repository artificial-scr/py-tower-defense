"""tools/select_tests.py: which tests a change runs."""

import glob
import importlib.util
import os

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("select_tests", os.path.join(HERE, "tools", "select_tests.py"))
select_tests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(select_tests)
ALL = select_tests.ALL
RUNTIME_FILES = {"settings.json", "savegame.json", "profile.json"}  # written by the game, ignored by git


def picked(*paths):
    return select_tests.select(paths)[0]


def test_a_soundtrack_change_runs_only_the_music_tests():
    assert picked("music.py", "music.json", "assets/music/meadow/build/pads.ogg") == [
        "tests/test_launch.py", "tests/test_music.py"]


def test_balance_changes_run_the_playthroughs_and_drawing_changes_dont():
    assert "tests/test_playthrough.py" in picked("towers.json")
    assert "tests/test_playthrough.py" in picked("monsters.json")
    drawing = picked("sprites.py", "terrain.py")
    assert "tests/test_rendering.py" in drawing and "tests/test_playthrough.py" not in drawing


def test_a_test_file_runs_itself():
    assert picked("tests/test_combat.py") == ["tests/test_combat.py"]


def test_deleted_test_files_arent_run():
    assert picked("tests/test_gone.py", "README.md") == []


@pytest.mark.parametrize("path", ["main.py", "tests/helpers.py", "tests/conftest.py", "pyproject.toml", "new.py"])
def test_shared_or_unknown_files_run_everything(path):
    assert picked(path, "music.py") == ALL


def test_docs_run_nothing():
    assert picked("README.md", "DESIGN.md", ".gitignore", ".gitattributes") == []


def test_every_file_of_the_game_has_a_rule():
    files = [os.path.relpath(f, HERE) for pattern in ("*.py", "*.json", "*.toml", "tests/*.py", "tests/*.json",
                                                      "tools/*.py", "assets/*/*")
             for f in glob.glob(os.path.join(HERE, pattern))]
    missing = [f for f in files if f not in RUNTIME_FILES and not select_tests.has_rule(f)]
    assert not missing, f"add these to RULES in tools/select_tests.py: {missing}"


def test_rules_name_real_test_files():
    for _, tests in select_tests.RULES:
        for t in () if tests == ALL else tests:
            assert os.path.isfile(os.path.join(HERE, "tests", f"test_{t}.py")), t


def test_the_report(capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["select_tests.py", "music.py", "README.md", "--", "-x"])
    assert select_tests.main() == 0
    out = capsys.readouterr().out
    assert "launch, music  <-  music.py" in out and "no tests  <-  README.md" in out
    assert "Run: uv run pytest tests/test_launch.py tests/test_music.py -x" in out, "pytest's own args after --"
