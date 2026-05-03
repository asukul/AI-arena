# `corpora/`

Hidden test data and reference corpora for each track.  **Never returned in
API responses** — only scores are.

## Layout

```
corpora/
├── gold/
│   ├── hallucination_hunter.json   # {claim_id: gold_label}
│   ├── prompt_golf.json            # added Day 3
│   ├── rag_treasure_hunt.json      # added Day 4
│   └── meta_judge.json             # added Day 6
└── isu_course_catalog/             # Track 3 corpus, chunked + indexed
```

`evaluator/gold.py` reads from this directory at runtime.  Rotating gold
labels between cohorts: drop in a new JSON, redeploy.  No code changes.

The starter file `gold/hallucination_hunter.json` matches
`tests/fixtures/sample_hallucination.json` so the smoke test scores 1.0
end-to-end.  Replace it with the real hidden labels before launch.
