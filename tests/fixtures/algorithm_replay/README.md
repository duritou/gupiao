# Algorithm replay fixtures

These snapshots are deterministic, anonymized contract samples for testing the
replay and promotion gates. They are not a performance claim and must not be
used as evidence that candidate is better than baseline.

`contract_samples.json` intentionally covers the five dates called out in the
audit (`2026-08-21`, `2026-08-24`, `2026-08-25`, `2026-08-31`, and
`2026-09-01`). The five-day sample must remain below the 20-day historical
gate. Any real promotion decision requires separately frozen production
snapshots with verified future labels.
