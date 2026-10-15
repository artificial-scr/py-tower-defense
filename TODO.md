# TODO

## Profile validation

`profile.json` is read with `data.get(..., default)` field by field, and anything unreadable throws the
whole profile away (`Profile.load`). Replace that with:

- a JSON schema for the profile, checked on load, with a clear message for what's wrong;
- default values for every field, so a profile from an older version gets the new fields filled in
  instead of being reset;
- a decision for profiles made before tower unlocks (DESIGN.md §11): keep every tower, or start
  over with the Gun only. Until then, a profile without `towers_unlocked` starts with the Gun only.
