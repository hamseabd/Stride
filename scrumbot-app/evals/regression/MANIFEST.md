# Regression Test Manifest

| ID | Bug | Fixed | Test |
|---|---|---|---|
| BUG-001 | `update_user_patterns()` reset `preferred_tone` to `"balanced"` even when user had explicitly set it to `"direct"` or `"encouraging"` | pre-v1.1 | `test_regression.py::test_bug_001_update_user_patterns_preserves_tone` |
| BUG-001b | Boundary: a user with no prior pattern must default to `"balanced"` (pins the other side of the BUG-001 fix) | pre-v1.1 | `test_regression.py::test_bug_001_boundary_new_user_defaults_to_balanced` |
