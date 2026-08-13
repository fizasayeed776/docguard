# Agent iteration log

This log records the prompt and reliability changes made to the Step 3 Gemini
consistency agents. It is intentionally factual: entries are derived from the
current implementation and should be extended whenever prompts or evaluation
results change.

| Date/step | Agent | Change | Reason / expected effect |
| --- | --- | --- | --- |
| Step 3 | Extractor | Constrained output to a JSON array with `statement`, `category`, and `confidence`; limited categories to endpoint, config value, process step, and version number. | Makes extracted claims machine-readable and limits vague opinions. |
| Step 3 | Comparator | Instructed it to retrieve semantically similar claims from other artifacts and label pairs consistent, contradictory, or unrelated with brief reasoning. | Separates candidate generation from final judgement. |
| Step 3 | Judge | Added conservative severity guidance and a false-positive option, including the example of intentionally coexisting API versions. | Reduces noisy inconsistency reports. |
| Step 3 follow-up | All Gemini-backed work | Added detection of quota/rate-limit errors and a clearly labelled `[heuristic]` fallback with confidence `0.0` for extraction. | Keeps the pipeline observable during free-tier exhaustion without presenting fallback claims as AI-validated. |

## Next measurement step

Create a versioned fixture with 5–10 document pairs covering known
contradictions, intentionally valid version differences, and unrelated claims.
For each case record expected detection, severity, and false-positive status.
Run Extractor → Comparator → Judge against the fixture after every prompt
change and record precision, recall, severity agreement, Gemini model/version,
and a representative failure here.
