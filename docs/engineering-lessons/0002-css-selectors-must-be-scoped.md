# 0002: Bare element selectors restyle every match
Status: proposed
Date: 2026-11-18
Area: front end (app.css)

Observed failure: making the sidebar sticky with `nav { position: sticky; height: calc(100vh - 56px) }` also hit the job
drawer's `nav.jIndex`, which then covered the drawer: 54 browser tests failed with "intercepts pointer events".
Root cause: an unscoped element selector in a stylesheet with several elements of that type.
Evidence: tests/e2e/e2e_drawer.py and others; Playwright logs naming `nav.jIndex` as the interceptor.
Correction: `body > nav { ... }`; a sticky top bar's z-index set under the drawer and viewer.
Lesson: scope new CSS to the element it is for (an id, a class or a child combinator); after a layout change run the
browser suite or `lodestar selfcheck` before reporting it done.
Promoted to: test (`e2e_selfcheck.SelfCheckPage.test_every_tab_and_part_is_clean` and the browser suite).
