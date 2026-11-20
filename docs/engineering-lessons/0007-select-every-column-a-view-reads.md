# 0007: A view reading a new column needs it in the query
Status: proposed
Date: 2026-11-18
Area: listings.py

Observed failure: All jobs answered HTTP 500 after `_view` began reading `novelty`; unit tests passed because they read
rows with `SELECT *`.
Root cause: `listings.query` selects a fixed column list (`LIGHT`).
Evidence: tests/e2e/e2e_novelty.py console error on /api/listings.
Correction: the new columns added to `LIGHT`.
Lesson: when a row view reads a new column, grep every query that feeds it; cover the path with the browser test that
loads the real endpoint.
Promoted to: test (`e2e_novelty.Novelty.test_all_jobs_shows_each_verdict`).
