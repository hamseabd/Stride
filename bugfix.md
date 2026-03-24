# Stride — Known Bugs

Bugs discovered during code review. Each entry includes the exact fix and which phase applies it.

---

## BUG-001: `update_user_patterns` resets `preferred_tone` on every weekly review

**File:** `shared/tools.py` — `update_user_patterns()` (~line 698)
**Severity:** Medium — silent data loss, no crash
**When it bites:** Phase 2, the moment tone adaptation starts writing `preferred_tone != "balanced"`
**Fix ships in:** Phase 2 (first thing, before any tone work)
**Status:** ✅ Fixed (2026-03-05, Phase 2)

### Root cause

`update_user_patterns` builds a fresh `UserPattern` object and calls `put_item`, which overwrites
the entire `PATTERN#AGGREGATE` record. The constructor is called without `preferred_tone`, so
Pydantic fills it with the model default: `"balanced"`.

Any `preferred_tone` value previously written by tone adaptation logic is silently wiped every
time the user completes a weekly review.

```python
# CURRENT — preferred_tone always reset to "balanced"
pattern = UserPattern(
    user_id=user_id,
    avg_pace=round(new_pace, 2),
    avg_completion_rate=round(new_rate, 2),
    common_blockers=merged_blockers,
    cycle_count=new_count,
    # preferred_tone not passed → defaults to "balanced"
)
```

### The fix

Read `preferred_tone` from the existing DynamoDB record before overwriting. Pass it through.

**Step 1** — add one line after the existing reads (~line 686):

```python
# CURRENT
old_count    = int(existing.get("cycle_count", 0)) if existing else 0
old_pace     = float(existing.get("avg_pace", 0.0)) if existing else 0.0
old_rate     = float(existing.get("avg_completion_rate", 0.0)) if existing else 0.0
old_blockers = existing.get("common_blockers", []) if existing else []

# NEW — add this line
existing_tone = existing.get("preferred_tone", "balanced") if existing else "balanced"
```

**Step 2** — pass it to the constructor:

```python
# CURRENT
pattern = UserPattern(
    user_id=user_id,
    avg_pace=round(new_pace, 2),
    avg_completion_rate=round(new_rate, 2),
    common_blockers=merged_blockers,
    cycle_count=new_count,
)

# NEW
pattern = UserPattern(
    user_id=user_id,
    avg_pace=round(new_pace, 2),
    avg_completion_rate=round(new_rate, 2),
    common_blockers=merged_blockers,
    cycle_count=new_count,
    preferred_tone=existing_tone,
)
```

No other changes. No model changes needed — `preferred_tone` already exists on `UserPattern`.

### Checklist — BUG-001

- [ ] Read `existing_tone` from DynamoDB record in `update_user_patterns()`
- [ ] Pass `preferred_tone=existing_tone` to `UserPattern(...)` constructor
- [ ] Verify: manually set `preferred_tone = "direct"` in DynamoDB, call `update_user_patterns`, confirm tone is preserved

---

*No known open bugs as of 2026-03-12.*
