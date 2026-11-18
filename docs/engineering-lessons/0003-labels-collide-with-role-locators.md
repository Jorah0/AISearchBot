# 0003: Accessible labels that contain another control's name
Status: proposed
Date: 2026-11-18
Area: front end (accessibility)

Observed failure: labelling a file picker "Resume file to import" made `get_by_role("button", name="Import")` match
both the picker and the Import button (strict mode violation): 3 profile-import browser tests failed.
Root cause: role/name lookups match substrings, and a file input has the button role.
Evidence: tests/e2e/e2e_profile_import.py; the Playwright message listing both elements.
Correction: the label became "Resume file (.docx, .pdf, ...)".
Lesson: an accessible name must describe the control without reusing a neighbouring button's words.
Promoted to: rule (`.claude/agents/lodestar-reviewer.md`, front-end invariant).
