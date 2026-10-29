# Original local dashboard candidate

The original GPL-3.0-only HTML/CSS/JavaScript implements fixed same-origin local
FsStorage project actions without external resources, telemetry, browser storage
or raw error logging. It bounds IDs, names, JSON responses and action lifetimes.
Unconfirmed transport cancellation permanently closes the controller to further
I/O until the page is reloaded. No browser/network join is claimed.

The explicit hosted `dashboard-unit` profile authenticates the existing pinned
Node24.19.0 carrier, executes the 25 manifest-bound JavaScript cases and requires
exact TAP names/totals with no skip, cancellation or todo. Eleven Python controls
exercise receipt commit and cleanup. Only a closed JSON receipt is uploaded; no
raw TAP or project payload. All tests execute on approved disposable runners.

This is unit evidence only. Actual Rust CRUD, native WebKit rendering/CSP,
accessibility, backend confinement and metadata atomicity remain unverified. The
current candidate rename uses fresh metadata and a full POST with numeric
roundtrip safeguards; it cannot prevent concurrent writers. The separately
reviewed typed backend rename will be integrated and tested explicitly later.
No signing/publication/hosting authority or full Studio acceptance is granted.
