# Real Silex export to offline Core site pack

This is a synthetic, explicitly selected hosted integration fixture. Source and
inert safety checks are implemented; **three hosted trials failed, most recently
at manual text interaction, and no export/pack acceptance has been obtained**.
It is not a product frontend, public hosting service or model/AI implementation.

The existing Core `Quality` workflow has an optional `studio_export_pack` manual
input. A reviewer supplies complete lowercase 40-hex `core_revision` and
`studio_revision`; Core must equal the workflow's source revision. The fixed
Silex commit is `672efed69dda04c0a1e968859239e042f00d9538` (v3.9.0).
Dispatch is a separate principal action after review; adding these sources does
not start a trial. Ordinary Quality checks retain their normal triggers and steps.

The original [run 39846266494](https://github.com/VOLPAROSSA/volparossa/actions/runs/39846266494)
is retained as failure evidence. It bound Core
`c15791672e9932edcb24b0fedbdf1090b975d058`, Studio
`024a478bcef20650197651b15f253133894fb06a`, and the fixed Silex revision.
Acquisition, inert checks, pinned Silex build and Core proof compilation passed;
the actual browser returned `TimeoutError` at `editor_load`. No edits, preview,
ZIP export or actual Core pack/decode were verified. Its receipt reports joined
server/browser groups, isolation, nonroot/capability checks and temporary output
removal. Chrome 155.0.8059.39 is an observed runner identity, not an immutable pin.

Source diagnosis found the fixture waited for `.silex-loading` to detach, although
the pinned HTML assigns that class to the body and never removes it. Pinned
`editor/index.ts` `loaded()` hides `.silex-loader` and reveals `#gjs` instead.
The correction waits for those actual visibility states without increasing a
deadline or changing editor behavior. This deterministic bad wait does not prove
that the original editor otherwise finished initialization; its combined stage
does not identify which navigation/readiness await raised. The candidate now
reports those separate closed stages, plus frame readiness, without URLs or DOM
content. A later reviewed trial must establish readiness and subsequent behavior.

The same run's ordinary Quality job failed full ShellCheck with SC2015 information
diagnostics on three Studio-only wrapper guards; Cargo formatting had passed.
Those guards now use explicit `if` statements, and the opt-in source check uses
full ShellCheck severity, matching the ordinary gate. Corrections are unexecuted
runtime candidates pending independent source review and principal dispatch.

The follow-up [run 39848640073](https://github.com/VOLPAROSSA/volparossa/actions/runs/39848640073)
also failed, at `editor_ready`, against Core
`721e867dc5f54b390283191cc0b7de21cbe91c3b` and Studio
`06dca77af8e98ee06956ccc56dc43a3ce41547d6`. Its retained receipt again reports
successful failure-path cleanup, with no manual edit/preview/export or pack/decode.
It contains no page-error evidence identifying the exact initialization failure.

Targeted source inspection found a second deterministic fixture problem:
`editor/grapesjs/index.ts` passes `config.fontsApiKey` into the always-initialized
fonts plugin; `grapesjs-fonts/src/fonts.js` synchronously throws on an empty
`api_key`. The old fixture explicitly selected that empty value. The corrected
configuration uses `VOLPAROSSA_SYNTHETIC_OFFLINE_FONT_TOKEN`, visibly a placeholder
with no service credential or authority. Both font service URLs remain the same
loopback-only disabled endpoints, and the trial selects system fonts. The normal
fonts plugin and manual controls remain present; remote font-service availability
is outside this fixture. This source-supported blocker is consistent with the
failure, but the retained receipt cannot prove it was the original exception.

The manifest records hashes of the exact pinned plugin registration, constructor
and configuration mapping. The controller checks them as an inert source contract
before any acquisition/execution and verifies the synthetic token and unchanged
loopback URLs. The next candidate retains fixed page-error categories, one known
missing-font-key boolean, capped counts (0–32), navigation completion and a fixed
inventory of read-only DOM/API-presence booleans. Its DOM probe has a 500 ms limit
inside the existing execution envelope; no existing deadline is increased. The
controller validates the diagnostic schema/types/bounds before retaining it.
No raw browser/server error text, logs, URLs, request IDs, HTML, assets or project
data are added to the receipt. Diagnostics are observations, not editor actions
or startup acceptance. Independent review is required before another hosted run.

The third [run 39850757186](https://github.com/VOLPAROSSA/volparossa/actions/runs/39850757186)
used Studio `d5103c7cea96bdbd973b74666be9e7f8fbc77d96` and the same Core revision.
Startup and page-creation UI actions returned; the browser then timed out in the
combined `manual_text` stage. Its closed snapshot showed a visible editor/frame,
hidden loader, and zero reported page, console, request or blocked-external-request
errors. All reported cleanup passed. These observations establish neither
persisted page correctness nor any text edit, preview, ZIP export or pack/decode.
The original artifact `12456039695` (963 bytes), SHA-256
`da35b2a608b2a13445d8938e6072f1435f45ec2ff34dd16dd4f0cd4bf254f881`,
is retained under Core `.git/ci-evidence/studio-export-39850757186/`.

The exact failed await remains unknown. A read-only audit of the **locked npm
archives**, verified against their SRI in pinned Silex's lockfile, established:

- GrapesJS 0.23.2 `ComponentView.updateAttributes()` renders `data-gjs-type` on
  canvas DOM. The existing text attribute selector was therefore valid; it is
  not an established defect. `FrameView._onRootMount()` attaches `Droppable` to
  the actual wrapper, whose rendered attribute is `data-gjs-type="wrapper"`.
- `grapesjs-blocks-basic` 1.0.2 defines Text as `type: 'text'`, `activate: true`.
  Pinned Silex `editor/grapesjs/blocks.ts` replaces its inline padding style with
  `silex-default-text`. GrapesJS `ComponentTextView` handles `dblclick` with
  `onActive`; the normal rich-text editor sets `contentEditable` to true.
- `BlockView` uses native drag events; ordinary block click does not append with
  the default `appendOnClick: false`. The fixture retains real mouse dragging
  and keyboard editing, without dispatched synthetic events or model mutations.

The manifest records registry URLs, archive SRI/SHA-256, registry source commits,
BSD-3-Clause license identities and extracted source-map `sourcesContent` hashes. These are
read-only source provenance, not added runtime downloads or runtime acceptance.
The candidate derives the drop position from the visible intersection of the
actual wrapper, frame and existing viewport. It distinguishes block-panel open,
block readiness, canvas readiness, dragging, text readiness, activation, keyboard
editing and commit stages. It waits for the actual text component and ordinary
RTE editable state before typing. Those checks preserve the existing 12-second
UI limit and enclosing runtime deadlines; they do not prove the former drop failed.

Failure-only diagnostics add six fixed DOM counts capped at 32 (blocks, Text
blocks, frames, wrappers, fixture text components and editable fixture text
components), plus wrapper/text visibility booleans. The same 500 ms snapshot
budget applies; the controller rejects unknown fields, out-of-range counts,
boolean-as-count and nonboolean flags. No DOM text, HTML, URLs, IDs, project data
or raw error is retained. Independent review and a paired reviewed Core/Studio
hosted trial remain necessary; no successful interaction is claimed here.

The hosted job acquires exact source and builds the actual Node Silex application,
using its frozen upstream lockfile and the exact app filter. Dependency install
scripts are disabled; only its reviewed `build:client`, `build:server`, and
`build:public` tasks are selected. The fixture uses Node 24.19.0 from the Core's
already recorded runtime, pnpm 10.34.4, and `playwright-core` 1.56.1. Manifest hashes
and package integrity/lock data bind these inputs. There is no browser installer:
missing installed GitHub-hosted Google Chrome fails the trial. The receipt records
the actual Chrome version, binary path/hash and browser engine version; the runner
browser is an observed dependency, not an immutable browser pin.

All generated Silex builds, dependencies, drafts, downloads and logs are inside one
new runner temporary tree. The configuration selects temporary FsStorage and only
DownloadConnector, replacing the subsequent default SaaS config with an empty
configuration through the supported user-config seam. Only the normal static
editor assets are served. FsHosting, FTP, GitLab, SaaS dashboard/onboarding,
credentials, MCP, signing, content publication and public connectors are absent.
CMS/11ty and external fonts are deselected for this static fixture; the normal
page, manual text/style, responsive controls, preview and other editor capabilities
are not replaced. This configuration does not disable those product requirements.

Core's existing namespace command wrapper starts the actual editor/server/browser
with loopback only, drops capabilities and kills descendants via a PID namespace
on timeout. No external interface/default route exists in that namespace. Browser
requests are additionally restricted to the exact loopback fixture origin, and any
attempt to request an external origin fails acceptance. Chrome sandboxing remains
enabled; an environment unable to support it fails without a `--no-sandbox`
fallback. Initial independent review found the default successful userns backend
maps UID 0, which sandboxed Chrome rejects. The corrected fixture explicitly selects
the fixed `--studio-nonroot-command` backend: only the `studio_export` command,
existing handoff marker, loopback, system Python and exact temporary runtime script
are allowed, with hosted-runner checks and the existing explicit sudo namespace
authorization. It skips the UID-0 probe and uses the existing namespace trampoline
to drop to the original nonroot runner UID/GID, clear capabilities and set NNP.
Default callers retain their original userns-first behavior. Actual hosted
sandbox/namespace compatibility remains unverified.

Plain sudo `env_reset` stays enabled. A fixed eight-key runtime context is written
to a new owner-only `0600` file inside the private temporary tree. The runtime
locates it from its own fixed script path, independently of environment variables,
and reads it only after checking the network namespace, original nonroot identity,
all five zero capability sets and NNP. It restores only validated fixture paths,
the fixed installed Chrome launcher, original runner home and a fixed system PATH
after privilege drop. There is no `sudo -E`, broad environment preservation or
pre-drop PATH injection. A reset-environment inert Python check verifies this data
handoff; actual sudo/namespace execution remains unverified.

The driver uses normal UI mouse/keyboard input to add a page, drag a Text block,
edit its visible content and font size, and enter preview. It reads computed
style only to verify the visible result; it does not inject editor project data,
components or publication payloads. The user-facing Publish dialog selects the
sole **Download zip file** connector. That upstream dialog label means a local
export in this fixture, and confers no VOLPAROSSA signing/publication authority.
The driver clicks the actual one-time link, consumes the real browser download,
and checks that the server no longer serves it. UI selectors and build/lock
compatibility remain executable questions until the reviewed hosted trial passes.

`extract.py` rejects traversal, ambiguous/hidden paths, duplicates, links/special
files, excessive ZIP size, entries, nesting and uncompressed file totals. It writes
only a new private tree and hashes every actual ZIP asset. The ignored Core test
executes the existing `volparossa content site pack` CLI, decodes its exact output
with production `SiteBundle::decode`, compares every asset's bytes/hash, checks
HTML/CSS types and the edited marker/style, and requires `network_published=false`.
It also exercises pack's existing no-clobber property. No packer implementation
or shared wire/interface fields change.

The trial retains one bounded public synthetic JSON receipt, including exact
source revisions, stage, checks and cleanup. It removes temporary dependencies,
projects, ZIPs and raw process logs; the receipt contains no source project data,
download URLs, keys or environment dumps. Child process groups are terminated and
joined on timeout/cancellation. Cleanup scans live session/group members and
escalates TERM to KILL even when the group leader has already exited; zombies
cannot execute and are excluded from live-member evidence. Complete ancestor
group/session namespace prefixes are captured from the unreaped direct child
immediately after spawn, before poll/wait. Its parent identity anchors capture;
prefix comparison excludes equal-depth sibling PID namespaces that reuse the same
inner IDs, while accepting nested descendants of the owned group. Inert parser
tests cover both cases without starting namespaces. The namespace wrapper provides a second kernel
cleanup boundary for server/browser descendants. GitHub runner destruction remains
the final cleanup boundary for uncatchable termination. The two failed startup
trials retain scoped cleanup observations; forced cancellation/crash and later
successful-runtime cleanup cases still require hosted verification.

Inert verification, allowed on the development host:

```sh
python3 -B integration/silex-export/test_contract.py
python3 -B integration/silex-export/test_lifecycle.py
python3 -B integration/silex-export/test_runtime_context.py
python3 -B integration/silex-export/test_wrapper_guard.py /absolute/path/to/reviewed/core
```

These parser tests manufacture synthetic ZIPs solely to exercise extraction
denials. They cannot serve as Silex output or runtime acceptance. Run no Node,
pnpm, browser, Silex, Rust build or hosted dispatch merely to inspect this fixture.
The lifecycle tests execute only inert Python fork/signal fixtures and adopt/reap
their own children, reproducing the exited-leader/TERM-resistant-child failure.
Wrapper tests execute only rejecting guards and never reach namespace creation or
sudo. None is actual editor, browser sandbox or network cleanup acceptance.
Context tests run only standard-library Python under a stripped environment;
they do not perform a real sudo handoff or privilege transition.

Build/install/process failures preserve an allowlisted operation label, numeric
exit status when a child executed, and a closed failure classification. Raw logs,
command arguments, paths and environment content are not included in diagnostics;
spawn failures use a null exit status because no child exit occurred.

A future passing receipt establishes only actual editor creation/edit/preview,
local export and offline Core packaging within this narrow synthetic case. It
does not close all of Studio cases 1/2/14, representative import/responsive/assets
coverage, any signed/network publication, independent peer retrieval/rendering,
publisher-offline availability, conventional/public hosting, DNS/TLS, updates,
withdrawal, protected shared AI, dynamic state or the other fifteen-case criteria.
