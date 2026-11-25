# The learning tree: how Lodestar's job model learns, builds and improves

A map of the tools that let the local job model (or whichever model you choose) learn from pulled information and
from your own decisions, apply proven job-search methods, and get measurably better. Built from two research passes
(2026-11-18); every claim below links its source in `lodestar/data/playbook.json` or in the references at the end.
Status: **built** (in Lodestar now), **next** (cheap, high value), **later** (needs more data or hardware).

## The rule at the root

Your own choices are the ground truth. A change counts as an improvement only when the evaluation (branch 5) moves on
decisions the model never saw. Everything stays on this machine; the salary floor, private answers, EEO and readiness
never enter anything the model learns from or that could be exported.

```text
Learning tree
├── 1. Sources: what it can pull (terms-safe)
│   ├── built  Job boards: Remotive, Arbeitnow, RemoteOK, HN Who is hiring, Jobicy, Himalayas, WWR, USAJOBS, Adzuna (key)
│   ├── built  Company ATS feeds: Greenhouse, Lever, Ashby, SmartRecruiters (Monitor > Companies)
│   ├── built  O*NET occupations and skills (bundled, CC BY 4.0); BLS OEWS pay (market_pay)
│   ├── built  Your mail (job-related, trust-checked), your profile, your applications and outcomes
│   ├── next   Indeed Hiring Lab datasets (CC BY 4.0, GitHub): posting trends by occupation and metro
│   ├── next   DOL OFLC H-1B / LCA disclosures (public domain): real offered wages by employer and title
│   ├── later  BLS Employment Projections and JOLTS; FRED labour series (free key)
│   ├── later  Company engineering blogs (RSS only, robots.txt first)
│   └── never  LinkedIn, Indeed, Glassdoor, ZipRecruiter, SimplyHired (terms); Levels.fyi (terms forbid AI and datasets);
│              scraped Kaggle dumps of those sites; a full Common Crawl
├── 2. Knowledge: what it knows
│   ├── built  Strategy playbook: evidence-graded methods (strong / moderate as advice, myths to correct, weak withheld)
│   ├── built  Your employer-safe profile and preferences (floor withheld) in the job model's message history
│   ├── next   Retrieval memory: nomic-embed-text (/api/embed, search_document / search_query prefixes) into SQLite
│   │          BLOBs, cosine in Python + FTS5 BM25, merged by reciprocal rank fusion; postings, notes, decisions
│   └── later  sqlite-vec 0.1.9 when the corpus outgrows brute force (needs enable_load_extension)
├── 3. Learning signals: what it learns from
│   ├── built  Pursued (applied and beyond; interviews and offers weigh most) vs passed on (rejected auto-track
│   │          proposals, withdrawn jobs)
│   ├── next   A one-line reason with each decision (why you passed): retrieved with similar postings
│   ├── next   Outcomes per channel: response rate by source, fit band, referral or not, tailored or not
│   └── later  Interview and offer outcomes per company type and role family
├── 4. Learners: how it changes
│   ├── built  Few-shot memory: your recent decisions in the model's message history (rebuilt daily)
│   ├── next   Dynamic few-shot: the k past decisions most similar to the posting being judged, per request
│   ├── next   Search bandit: Thompson sampling (Beta(wins+1, losses+1)) per saved search and board picks what
│   │          to run, wins = postings you pursue
│   ├── later  Learned re-ranker: logistic regression on explicit features (fit parts, pay vs floor locally,
│   │          place match, similarity to pursued minus passed, the LLM's score), from about 50 labelled decisions
│   ├── later  Prompt optimisation offline with DSPy BootstrapFewShot (dev tool, not shipped)
│   └── later  LoRA fine-tune (Unsloth, KTO for unpaired pursued / passed labels) exported to GGUF and loaded with the
│              Modelfile ADAPTER line: only past about 1,000 outcomes, an NVIDIA GPU (about 8 GB for a 3B model),
│              and only if branch 5 shows it beats retrieval + re-ranker
├── 5. Evaluation: how improvement is proven
│   ├── built  Held-out pairwise accuracy (= ROC AUC) of the job model vs its base (Setup > Local job model > Evaluate)
│   ├── next   Time-based split (learn the past, test later decisions) and precision@k of the ranking
│   ├── next   Results kept per model and prompt version, so a rebuild that scores worse is not used
│   └── later  Inspect AI for logged, repeatable evals (dev time)
├── 6. Reliability: how its decisions stay trustworthy
│   ├── built  Every AI text through the salary-floor guard; facts only from the profile (resume.check_rewrite)
│   ├── built  AI cross-check: other linked AIs review an answer until all agree (pref ai_crosscheck)
│   ├── next   Ollama structured outputs (format = JSON schema, temperature 0, validate and retry once)
│   └── next   think = false (or strip) for reasoning models so verdicts parse
└── 7. Strategy improvement: how the search itself gets better
    ├── built  Search breadth: Target roles, remote-in-a-region, place + radius, seniority from experience
    ├── built  Ghost-job signals (stale, reposted) discounted; early applying through Autopilot's daily runs
    ├── next   Weekly strategy review: the job model reads your outcome stats + the playbook and proposes one change
    │          (broaden, narrow, seek referrals, apply earlier) as an Inbox suggestion, never applied by itself
    └── later  Referral finder: your contacts at companies you pursue, surfaced before you apply
```

## Order of work

1. **Retrieval memory + dynamic few-shot** (branches 2 and 4): biggest gain for the least code; no new dependency.
2. **Structured outputs** (branch 6): fewer unparseable verdicts from small local models.
3. **Search bandit + outcome stats** (branches 3, 4, 7): the search learns which queries and boards pay off.
4. **Time-split evaluation per version** (branch 5): the gate every later change must pass.
5. **Weekly strategy review** (branch 7).
6. **Re-ranker** (about 50 decisions), then, if the data and hardware are there, a **LoRA** (about 1,000).

## Tools considered and set aside

- llama.cpp's own fine-tuning: deprioritised upstream (2026).
- MLX (Mac only), Axolotl (Linux-first): not for a Windows desktop.
- DSPy MIPROv2 under about 200 examples; DPO without real chosen / rejected pairs.
- Any hosted vector database or cloud grader: breaks the local-only rule.
- An LLM judge as the main metric: your actual choices are the ground truth.
- Long autonomous tool loops on 3-8B models: unreliable; Lodestar keeps fixed pipelines where code decides the steps.

## References (tools)

- Ollama embeddings and nomic-embed-text: https://ollama.com/library/nomic-embed-text
- Ollama structured outputs: https://docs.ollama.com/capabilities/structured-outputs
- Ollama tool calling: https://docs.ollama.com/capabilities/tool-calling
- sqlite-vec: https://github.com/asg017/sqlite-vec ; hybrid search with FTS5 + RRF:
  https://alexgarcia.xyz/blog/2024/sqlite-vec-hybrid-search/index.html
- DSPy: https://github.com/stanfordnlp/dspy ; BootstrapFewShot: https://dspy.ai/current/api/optimizers/BootstrapFewShot/
- Unsloth (Windows install, GGUF export to Ollama): https://unsloth.ai/docs/get-started/install/windows-installation
- KTO trainer (unpaired labels): https://huggingface.co/docs/trl/en/kto_trainer
- llama.cpp training status: https://github.com/ggml-org/llama.cpp/issues/13485
- Inspect AI: https://github.com/UKGovernmentBEIS/inspect_ai
- Thompson sampling tutorial: https://web.stanford.edu/~bvr/pubs/TS_Tutorial.pdf
- Data sources: O*NET https://services.onetcenter.org/ ; BLS https://www.bls.gov/developers/ ; Indeed Hiring Lab
  https://github.com/hiring-lab ; DOL OFLC https://www.dol.gov/agencies/eta/foreign-labor/performance ; FRED
  https://fred.stlouisfed.org/docs/api/fred/ ; Levels.fyi terms (excluded) https://www.levels.fyi/about/terms.html
