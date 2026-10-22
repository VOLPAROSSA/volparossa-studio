# Real Silex export to offline Core site pack

This is a synthetic, explicitly selected hosted integration fixture. Source and
inert safety checks are implemented; **no runtime acceptance has been obtained**.
It is not a product frontend, public hosting service or model/AI implementation.

The existing Core `Quality` workflow has an optional `studio_export_pack` manual
input. A reviewer supplies complete lowercase 40-hex `core_revision` and
`studio_revision`; Core must equal the workflow's source revision. The fixed
Silex commit is `672efed69dda04c0a1e968859239e042f00d9538` (v3.9.0).
Dispatch is a separate principal action after review; adding these sources does
not start a trial. Ordinary Quality checks retain their normal triggers and steps.

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
the final cleanup boundary for uncatchable termination. Cleanup observations and
forced cancellation behavior still require hosted verification.

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
