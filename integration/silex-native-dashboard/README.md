# Original local dashboard candidate

The original GPL-3.0-only HTML/CSS/JavaScript implements fixed same-origin local
FsStorage project actions without external resources, telemetry, browser storage
or raw error logging. It bounds IDs, names, JSON responses and action lifetimes.
Unconfirmed transport cancellation permanently closes the controller to further
I/O until the page is reloaded. No browser/network join is claimed.

The explicit hosted `dashboard-unit` profile authenticates the existing pinned
Node24.19.0 carrier, executes the 27 manifest-bound JavaScript cases and requires
exact TAP names/totals with no skip, cancellation or todo. Eleven Python controls
exercise receipt commit and cleanup. Only a closed JSON receipt is uploaded; no
raw TAP or project payload. All tests execute on approved disposable runners.

Rename uses the pinned Rust API's `GET /api/connector/?type=STORAGE`, with at most
16 connector rows and 64 KiB of streamed JSON, within the same original 15-second
action deadline. A unique `fs-storage` row of type `STORAGE` must explicitly report
`supportsWebsiteRename: true`. Only then does the app send
`POST /api/website/rename?websiteId=ID&connectorId=fs-storage` with exactly `{name}`.
It neither reads `/api/website/meta` nor sends a full metadata replacement. Missing
or false capability disables Rename until a successful refresh; other project
actions remain available. Malformed capability data cannot permit a rename POST.
Icons, login URLs and other connector metadata are never rendered or followed.
This feature flag provides API availability information, not permission authority.

Lossless preservation of existing metadata is the separately reviewed backend's
responsibility. This client change does not establish cross-process concurrency,
protection from a later stale full-metadata POST, or backend atomicity. Actual Rust
CRUD, native WebKit rendering/CSP, accessibility and backend confinement require
their own hosted evidence. No signing/publication/hosting authority or full Studio
acceptance is granted.

The original 25-case [run 40821942219](https://github.com/VOLPAROSSA/volparossa-studio/actions/runs/40821942219)
belongs to immutable Studio source `0c70576b63a47142ad752b34683b4c081328ea15` and its
original manifest. It exercises the older full-metadata rename client and does not
verify this name-only/capability source. Its evidence remains separate; the updated
27-case manifest requires a new exact-source hosted run. No local JavaScript,
browser, application or build execution is part of preparing this change.

The separate explicit `dashboard-compose-unit` profile executes eighteen Python
controls for copying only the three authenticated original application assets
into an empty disposable Silex dashboard directory. It provisions no SDK, Node,
compiler or Silex checkout. These controls cover bounded reads, exact assets,
FD ownership, cancellation, observed directory replacement and source drift.
Any adapter exception requires abandoning the disposable source tree; complete
rollback and cross-process race immunity are not claimed. A future native build
composition remains separate and requires its own review and actual evidence.
