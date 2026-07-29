# Classification evaluation

Regression data is versioned JSONL containing synthetic/redacted inputs and expected vendor, type, and jurisdictions. Run:

```powershell
python -m app.cli.classification_eval --dataset tests/fixtures/classification_eval_v1.jsonl
```

The offline runner reports exact matches, type/vendor accuracy, and state precision/recall without any provider call. Promotion gates should also track field precision/recall, correction rate, confidence buckets, confusion matrix, latency/cost, and prompt-injection cases. Never place production email bodies in a checked-in dataset.
