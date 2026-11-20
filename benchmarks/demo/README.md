# demo benchmark

A 5-item trivia benchmark with exact-match scoring. Exists so the
framework's run loop can be smoke-tested end-to-end without depending
on a clinical dataset or external API beyond the model client itself.

Run it:

    arisekit eval demo --model gpt-4o-mini --limit 5

Resume semantics: killing mid-run and rerunning re-uses the partial
JSONL at `results/raw/demo/<model>.jsonl`. Only items that errored or
weren't reached get retried.
