# Security policy

`splitguard` is local-first and treats dataset content as untrusted data. It
does not execute strings, import tool-call arguments, follow URLs, start
servers, or make network requests. Reports intentionally omit record text.

Please avoid sharing reports that contain sensitive file paths, hashes, or
record IDs. Use `--show-ids` only when the IDs are safe for the destination.
The matcher is not a guarantee of privacy or complete contamination detection;
review the input and report under your own data-handling policy.

To report a vulnerability, open a private security advisory on the GitHub
repository rather than publishing exploit details in a public issue.
