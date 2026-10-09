# Optional Jev helper

Read this only when using [consult_jev.py](../scripts/consult_jev.py). The helper
validates and sends a prepared Choice-only request using the maintained policy;
it does not implement other primitives or dispatch workers. Python and PyYAML are
skill dependencies separate from the native Go installation manager. Missing
dependencies do not justify automatic installation.

`--dry-run` validates without network access. A real call follows the entrypoint's
single-attempt, 30-second deadline, model pin, response validation, and task-sharing
rules. Prepare exact task evidence rather than asking Jev to generate code or new
findings. Other primitives follow the installed TypeSafe guide.

The helper writes only to the supplied task output path. Its record excludes the
authorization header, raw errors, and unknown response fields, but retains the
prepared request verbatim. Sanitize inputs before sharing or recording them:
the helper cannot remove credentials or sensitive material embedded in evidence.
Saving outside the agreed task location needs its own scope. Keep advisory results
and the coordinator's disposition separate from independently verified conclusions.
