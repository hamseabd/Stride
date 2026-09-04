# Regression Test Manifest

| ID | Bug | Fixed | Test |
|---|---|---|---|
| BUG-001 | `update_user_patterns()` reset `preferred_tone` to `"balanced"` even when user had explicitly set it to `"direct"` or `"encouraging"` | pre-v1.1 | `test_regression.py::test_bug_001_update_user_patterns_preserves_tone` |
| BUG-001b | Boundary: a user with no prior pattern must default to `"balanced"` (pins the other side of the BUG-001 fix) | pre-v1.1 | `test_regression.py::test_bug_001_boundary_new_user_defaults_to_balanced` |
| BUG-002 | Tools trusted the model-supplied `user_id`; a prompt-injected SMS could direct the agent at another user's records | 2026-09 (v2.3) | `test_regression.py::test_bug_002_tool_ignores_model_supplied_user_id` |
| BUG-003 | Pre-loaded context listed projects and tasks without ids; the agent guessed `project_id`/`task_id` (passed a project name, fabricated slugs) and reported success on calls that failed | 2026-09 (v2.3) | `test_regression.py::test_bug_003_context_exposes_ids_the_tools_need` |
