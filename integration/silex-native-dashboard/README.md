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

Root project actions use canonical `/api/website` (without a trailing slash),
matching the pinned Axum 0.8.8 nested root route and existing Silex MCP caller.
The full server has no path normalizer; this app does not depend on redirects or
try an alternate URL after failure. Named subroutes remain `/api/website/rename`
and `/api/website/duplicate`.

Rename uses the pinned Rust API's `GET /api/connector?type=STORAGE`, with at most
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
27-case manifest requires a new exact-source hosted run. The earlier 27-case
[run 40823831173](https://github.com/VOLPAROSSA/volparossa-studio/actions/runs/40823831173)
belongs to source `aed4119e46b7d8164b24b23108d465701faa3848`, before the canonical
root-URL correction. Those unit fixtures did not establish matching real-server
routes. Their evidence is preserved separately and does not verify this URL delta.
Actual Rust route/CRUD evidence remains necessary. No local JavaScript, browser,
application or build execution is part of preparing this change.

The separate explicit `dashboard-compose-unit` profile executes eighteen Python
controls for copying only the three authenticated original application assets
into an empty disposable Silex dashboard directory. It provisions no SDK, Node,
compiler or Silex checkout. These controls cover bounded reads, exact assets,
FD ownership, cancellation, observed directory replacement and source drift.
Any adapter exception requires abandoning the disposable source tree; complete
rollback and cross-process race immunity are not claimed. A future native build
composition remains separate and requires its own review and actual evidence.

The explicit `local-native-build` profile composes the separately verified FS
overlay and three original application assets, then builds the frontend and an
offline locked native release using the existing authenticated carriers and SDK.
The normal SDK receipts and fresh installed-version query gate the build helper.
Full metadata has its own single-group scope; all owned groups participate in
terminal cleanup. Accounting and terminal handoff preserve the first failure and
reject queued cancellation before committing a success receipt. Twenty-one caller
controls include the actual shared source-checker hook and cancellation seams.

The source snapshot allows only four existing generated schema paths to change;
all other tracked inputs, the nine added FS/publication helper paths, root and
nested locks, and the exact original assets remain bound. The ELF is inspected
privately and never launched or uploaded. Five JSON receipts only are artifacts.
Application execution, GUI/privacy, actual dashboard CRUD, native signing consent,
publication, redistribution, release and full Studio acceptance remain false.
The earlier native66f genuine-dashboard build remains separate evidence.

The first native composition40829260837 failed with E0599: locked Reqwest0.13.2
requires an optional query feature for RequestBuilder.query. The corrected MCP
call uses the existing url dependency; all Cargo manifests and locks stay fixed.
After the release compile, three actual desktop-bin tests verify query encoding,
closed parse errors and POST construction without sending a request. Their exact
names/counts and zero ignored/filtered cases gate acceptance. Test binaries are
separate from application startup; no GUI or MCP network session is inferred.
The unchanged server source closure reuses its32-test result from40826860067.

The explicit `dashboard-crud` disposable hosted profile compiles an original
Rust example against the actual Silex server library, using its public router.
It runs the original dashboard in the installed Chrome with its sandbox requested,
through the unchanged Core NET/PID fixture wrapper pinned to e58d1c9. Two server
and browser runs exercise create, typed rename, raw unrelated-byte preservation,
duplicate, persistence across restart and delete, plus42 invalid-ID HTTP denials.
The temporary example is removed and exact source inputs rechecked before success.
Eighteen Python controls precede provisioning. Only bounded JSON receipts leave
the runner; no application binaries, payloads, screenshots or raw logs are artifacts.
This profile installs no SDK and downloads no browser. Installed Chrome identity
is observed rather than represented as source authentication. It does not prove
native WebKit/GUI, mount/IPC/private-proc isolation, no external attempts, native
privacy/consent, production server CLI, publication or full Studio acceptance.
Actual hosted evidence remains required; source review alone is insufficient.
