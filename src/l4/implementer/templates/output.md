version: 1

# Output
Give the result of this step as one JSON object with "status" and "summary": "status" is "done" when you did the step, or "blocked" when you need an answer from a person (then "questions" holds at least one question), and "summary" tells in one to three sentences what you did.
Add "criteria_ids" (the criterion ids that your tests trace), "suppressions" (each new `# noqa` or `# type: ignore` that you added) and "notes_for_verifier" when you have them.
The object must conform to this JSON Schema: {schema}
Write your result object to `{path}`.
