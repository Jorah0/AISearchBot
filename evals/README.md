# Golden-task evaluations

A small, versioned set of real tasks on this repository that tells whether a change to how Claude works here (CLAUDE.md,
`.claude/` rules, agents, skills, hooks, the model) made it better or worse. Run with `python scripts/eval.py`
(see its header). `dataset/` holds the tasks; `reports/` the run results (not committed); `baseline.json` the pass
rates the next run is compared with.

Each task: `prompt` (what the agent is asked), `setup` (a planted defect or hostile text), `hidden_tests` (copied in
only after the agent finished), `checks` (commands that must pass), `forbidden` (`unchanged` paths, `only_change`
paths, `added_text` that must not appear), `reference` (the known-good change, used by `validate`), `split`
(`dev` for iterating, `heldout` to check you did not tune to the dev tasks).

Rules: `python scripts/eval.py validate` must say OK for every task (it fails as planted, passes with the reference);
no real data, keys or personal details in a task; add a task when a real mistake is found (docs/engineering-lessons),
and never edit a held-out task to make a run pass. Repeat a run (`--repeat 3`) before trusting one difference.
