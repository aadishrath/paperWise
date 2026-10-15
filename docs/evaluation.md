# Evaluation starter set

Use `examples/product-handbook.md` as the corpus. After the local stack has indexed it, run `docker compose exec api python scripts/evaluate.py`. The script reports source hit rate, expected-phrase recall, and citation validity for each case and as aggregate metrics. Record model names and `MIN_RELEVANCE_SCORE` when comparing runs.

| Question | Expected evidence | Expected answer facts |
| --- | --- | --- |
| How long do customers have to return an unused item? | Returns section | 30 days from delivery |
| Which items cannot be returned? | Returns section | Final-sale items and gift cards |
| How long can a refund take to appear? | Returns section | Five to seven business days after inspection |
| When is customer support available? | Support section | Weekdays, 9 a.m.–5 p.m. Pacific Time |
| Does the handbook say returns are accepted after 30 days? | Returns section | It does not; clearly say the source gives a 30-day window |

The current script measures evidence/source hit rate and expected-phrase recall; it does not claim to measure semantic correctness or unsupported claims. Add expert-reviewed ground truth, retrieval recall@k, answer correctness, and unsupported-claim review before using this as a model-quality benchmark. Ragas or DeepEval can be optional local evaluation tools; keep the deterministic set independent of external models and hosted services.
