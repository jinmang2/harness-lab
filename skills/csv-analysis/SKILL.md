---
name: csv-analysis
description: Write and verify a small Python program that analyzes CSV data robustly (dedupe, filter, aggregate, record bad rows). Use for CSV/order/sales analysis requests.
---

# CSV analysis program

1. Write the program with only the standard library (`csv`, `decimal`, `datetime`, `collections`).
2. Treat every field as untrusted: parse amounts with `Decimal`, quantities with `int`, dates with `date.fromisoformat`; a row that fails goes to an error list with its line number and reason, and the program keeps going.
3. Apply business rules in this order: invalid-row check -> duplicate id (keep first) -> status filter -> aggregate.
4. Create a test CSV that covers every rule (valid, duplicate, cancelled, bad amount, bad quantity, bad date), run the program on it, and compare the printed totals with values you computed by hand.
5. Report: files written, how you ran them, the actual output, and whether it matched.
