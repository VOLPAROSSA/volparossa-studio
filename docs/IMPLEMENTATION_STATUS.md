# Studio implementation status

Updated 2026-10-22. Requirements are the complete permanent
[Studio/hosting amendment](https://github.com/VOLPAROSSA/volparossa/blob/main/docs/development/STUDIO_HOSTING_REQUIREMENTS.md),
incorporated by the full Core goal. This file records Studio evidence and next
work, without replacing that scope or the shared Core execution ledger.

## Verified starting state

- Initial main `97ddafa6a317e151c1352e0ac61978ddc3bd79f0`, tree
  `5beb714ad1cf5a9e1a9bb38b204e493c4ec5bdf8`, contains README and GPLv3 LICENSE only.
  No previous integration, application runtime or Actions workflow existed there.
- Upstream Silex v3.9.0 resolves to `672efed69dda04c0a1e968859239e042f00d9538`.
  Source inspection covers GrapesJS editor, JS/TS plugins and Node publication API,
  Tauri/Rust desktop hosting connectors, MCP HTTP/stdio/evaluation bridge and
  component license notices. See [upstream.lock.json](../upstream.lock.json) and
  the [Core audit](https://github.com/VOLPAROSSA/volparossa/blob/main/docs/services/STUDIO_HOSTING.md).
  No dependency install, build, editor execution or publication was performed.
- Core already contains bounded signed site packaging, named retrieval, an isolated
  static viewer and public custody/owner-driven retention. Historical source-scoped
  tests are recorded in the Core content guide; none is Studio end-to-end acceptance.

## Implementation and acceptance still required

### Export-to-Core fixture candidate — 2026-10-22

Source bases: Studio `0268d2488cbbda7edbb95071221deb504fb3ace3`, Core
`c730617af48bf2d1771b24bc91fd450afb140db4`, Silex
`672efed69dda04c0a1e968859239e042f00d9538`. Isolated candidate worktrees are
`studio-export-pack-20261022` and `core-studio-export-pack-20261022` under Core's
`.volparossa-dev/worktrees/`. No commit, dispatch, installation or runtime evidence
is implied by these candidate names.

- Implemented [hosted fixture](../integration/silex-export/README.md): actual pinned
  Node Silex, fixture-only static configuration, temporary FsStorage and sole local
  DownloadConnector. Ordinary browser page creation/manual text/style/preview and
  the actual ZIP download feed safe extraction and existing Core `content site pack`.
- Core's existing Quality workflow gains an explicit opt-in exact-source-bound job
  and an ignored CLI integration test using actual `SiteBundle::decode`, complete
  asset inventory hashes, edited marker/style and `network_published=false`.
  No shared interface/wire/packer behavior is changed.
- Passed locally: 12 inert Python tests for extraction safety, bounds, exact hashes,
  source syntax and manifest/lock identities; seven inert Python process lifecycle
  tests, three reset-environment/private-context tests and seven rejecting wrapper
  guard tests; Core workflow YAML, shell syntax,
  ShellCheck and standalone Rust formatting. These are synthetic/parser/source
  checks and establish no editor/export or real sandbox/network cleanup acceptance.
- Pending after the first failed hosted trial: independent review of the narrow
  readiness/shell corrections, actual editor readiness/manual edit/preview/export,
  actual Core CLI/decoder result and broader normal/cancellation cleanup cases.
- Initial independent review found the successful userns probe deterministically
  maps UID 0, incompatible with sandboxed Chrome. Corrected source adds the fixed
  Studio-only nonroot command option to the existing Core namespace wrapper,
  using its explicitly authorized sudo trampoline and original runner UID/GID,
  cleared capabilities and NNP; ordinary callers retain their default behavior.
  No sandbox bypass or browser download fallback is selected.
- Initial cleanup review found TERM-resistant descendants survived when their
  leader exited. Corrected source drains the live process group independently of
  leader exit, escalates to KILL within bounded deadlines, and treats zombies as
  non-executing. Inert reproductions pass; hosted cleanup remains unverified.
  Failed install/build operations now retain closed labels/exit codes/classifications
  without raw logs, source paths or secrets. These corrections require independent
  re-review before a hosted trial; no review/acceptance is inferred here.
- Second review found sudo's default environment reset loses fixture paths, and
  namespace depth/inner group IDs can alias unrelated sibling PID namespaces.
  Corrected source uses a fixed owner-only context file read only after privilege
  checks, without preserving broad sudo environment or injecting pre-drop PATH.
  Group identity now captures the direct leader's full ancestor group/session
  prefix before poll/wait; parser tests reject sibling aliases and accept owned
  nested descendants. Reset-environment tests exercise the fixed data handoff
  only; actual sudo/sandbox/network cleanup still requires another independent
  source review and the separately selected hosted trial.
- A future passing narrow receipt would prove synthetic local editor/export/offline
  packaging only. All fifteen complete acceptance cases remain open; no signing,
  network publication, public hosting, independent peer rendering, private shared
  AI, publisher-offline availability or dynamic execution is established.

### First hosted export trial — failed, retained

[Original run 39846266494](https://github.com/VOLPAROSSA/volparossa/actions/runs/39846266494)
bound Core `c15791672e9932edcb24b0fedbdf1090b975d058` (tree
`087a58925beaf8c68f6174a450220c81c4be44d7`), Studio
`024a478bcef20650197651b15f253133894fb06a` (tree
`cdb2326707ada5164345f1bc1a363cca770e18d5`), and unchanged Silex
`672efed69dda04c0a1e968859239e042f00d9538`.

- Opt-in job `120060244063` passed source acquisition/binding, inert tests, pinned
  Silex build and Core pack-proof compilation. Actual sandboxed Chrome
  `155.0.8059.39` launched, but its receipt records `TimeoutError` at `editor_load`.
  No page creation/edit/preview/ZIP export or actual pack/decode passed.
- Its original artifact `12454998636` is 773 bytes, SHA-256
  `d4b033946c42353a4275861fc910032e30725c4e64917bbb3c1dd9fb3ce12eba`.
  Retained locally under Core `.git/ci-evidence/studio-export-39846266494/`.
  Receipt observations: server joined, server/browser driver groups drained,
  isolated network namespace, nonroot UID, cleared capabilities and temporary
  outputs removed. This is cleanup evidence for this failure path, not completion
  of cancellation/crash or full Studio/network acceptance.
- Source tracing identified an impossible readiness wait: `.silex-loading` is a
  permanent body class in this pinned release. `editor/index.ts` `loaded()` instead
  hides `.silex-loader` and reveals `#gjs`. The candidate now waits for those real
  states, with all existing time limits and manual controls preserved. This fixes
  the deterministic selector mismatch without claiming the failed browser had
  otherwise completed initialization.
- The original combined `editor_load` stage cannot identify the exact failing
  await. The candidate reports separate closed navigation/readiness/frame stages;
  it adds no URL, raw DOM, asset or private project-log diagnostics.
- Ordinary Quality job `120060244414` failed `scripts/check-shell.sh`: full
  ShellCheck reported SC2015 at wrapper lines 55, 66 and 67. The earlier warning
  threshold omitted information-level diagnostics. Cargo formatting completed
  successfully before the shell check ran. Original public job log was fetched
  and retained as `quality-job-120060244414.log`, 87,725 bytes, SHA-256
  `a1915f6fca020e555a50099e351186fa2de319f9b261192b6787551e87da1109`.
  The three guards now use explicit `if` statements; the opt-in wrapper source
  check uses full ShellCheck severity. Ordinary Quality steps remain unchanged.

These corrections need independent source review. No rerun, publication or new
runtime acceptance accompanies this diagnosis; the original failure stays retained.
Post-diagnosis checks pass: seven inert wrapper rejection tests, twelve existing
contract/parser checks, wrapper shell syntax and full-severity ShellCheck,
workflow YAML/Bash/ShellCheck and whitespace checks. Pinned source inspection
confirmed the actual readiness hook and editor route; no browser or Rust build
was executed locally to validate the correction.

### Follow-up hosted export trial — failed, retained

[Run 39848640073](https://github.com/VOLPAROSSA/volparossa/actions/runs/39848640073),
job `120068576367`, bound Core `721e867dc5f54b390283191cc0b7de21cbe91c3b` and
Studio `06dca77af8e98ee06956ccc56dc43a3ce41547d6`, with the same pinned Silex.
The actual browser failed `TimeoutError` at `editor_ready`. No manual page edit,
preview, ZIP export or actual Core pack/decode was verified. Cleanup fields again
report joined/drained groups, isolation, nonroot/capability checks, no cleanup
error and temporary output removal; this remains one failure-path observation.
Original artifact `12455893482`, 773 bytes, SHA-256
`18ecd38d8ae48f189acee81cd6e0b6fb6b0e3fbfc10d9bedb7956988a1f1a15c`, stays
under Core `.git/ci-evidence/studio-export-39848640073/` without replacement.

Targeted source diagnosis found the fixture selected an empty `fontsApiKey`,
which is passed to the pinned fonts plugin's `api_key`. That plugin is always
initialized and synchronously throws if the value is empty, before editor load
can complete. The candidate uses the explicit synthetic offline token while both
existing service URLs stay loopback-only; it adds no real key, remote service,
fallback, timeout change or altered manual editing. Manifest source hashes bind
the registration/constructor/configuration dependency and its inert contract.
The failure receipt lacks page-error evidence, so this source-supported blocker
must not be represented as a confirmed original runtime exception or a verified
startup fix.

The candidate adds closed startup diagnostics: fixed error categories, one known
missing-font-key classification boolean, capped counts, navigation completion and
read-only DOM/API-presence booleans only. There are no raw error messages/logs,
URLs, request identifiers, HTML, assets or project payloads. A bounded DOM probe
runs inside the existing execution envelope; controller validation rejects wrong
types, fields, categories and count limits before receipt retention.
Fifteen inert parser/contract/diagnostic checks and the actual pinned font source
hash contract pass locally. No Node, browser, build, privileged/runtime/network
namespace or new hosted trial was executed for this correction. Another independent
source review is required before principal dispatch; no Core source was changed.

All fifteen cases in amendment section 8 remain open for this integration:
create/import; edit/preview; explicit authorization; Core signed publication;
independent complete browser rendering; documented publisher-offline availability;
atomic updates; rejection of unauthorized/stale/forged revisions; failed-deployment
continuity; resource fairness; real shared-AI editing; independent pre-publication
review/tests; private data protection; portable export; recovery/withdrawal/cleanup.
Useful dynamic forms/APIs, server execution and durable application state have
separate Compute/Storage/availability requirements. No global uptime, censorship
resistance, public HTTPS or confidential execution claim is established.

## Active execution order

1. Review the selected Silex build/dependency/license boundary on approved hosted
   runners; preserve normal manual editing and portable preview/export.
2. Implement the scoped Silex export/hosting-connector-to-Core publication contract
   using existing site/named/custody interfaces and explicit signing authority.
3. Exercise real editor, publisher, independent identities/peers and browser rendering;
   prove complete asset retrieval after the publisher goes offline under stated bounds.
4. Complete updates/retention repair/rollback/withdrawal and honest availability status;
   retain original expiry, anti-replay floors and participant resource budgets.
5. Integrate shared Core AI and Code/OpenCode through permission-scoped supported MCP
   tools, private processing protections and independently reviewed changes.
6. Add useful Browser/Cloud/Code/Image/Mail/DPS/Map/other application paths; extend
   dynamic hosting when authorized execution and durable state are ready.

This order is adaptable. Existing critical Core Storage, protected Compute, network
and DPS integrations stay active and must not be discarded or needlessly restarted.
Do not install Silex or change the development host to satisfy these acceptance cases.
Present evidence includes source/inert checks, pinned hosted builds and two failed
browser startup trials with their scoped cleanup receipts. Actual manual editing,
preview/export/Core packaging acceptance and the full requirements remain incomplete.

### Third hosted export trial — manual interaction failed, retained

[Run 39850757186](https://github.com/VOLPAROSSA/volparossa/actions/runs/39850757186)
bound Studio `d5103c7cea96bdbd973b74666be9e7f8fbc77d96` and Core
`721e867dc5f54b390283191cc0b7de21cbe91c3b`. Startup and create-page UI actions
returned, then `manual_text` timed out. The closed snapshot showed visible
editor/frame, hidden loader and zero reported page/console/request/external-block
errors; all reported cleanup passed. Persistent page correctness, text/style
editing, preview, export and actual Core pack/decode remain unverified.
Original artifact `12456039695`, 963 bytes, SHA-256
`da35b2a608b2a13445d8938e6072f1435f45ec2ff34dd16dd4f0cd4bf254f881`,
is retained under Core `.git/ci-evidence/studio-export-39850757186/`.

Read-only locked GrapesJS 0.23.2/basic-blocks 1.0.2 source inspection confirms
`data-gjs-type` is rendered canvas DOM, the Text block's type/activation contract,
Silex's `silex-default-text` class and normal dblclick/RTE editable behavior.
The old selector is not a demonstrated defect; the exact failed await is unknown.
The source candidate instead resolves the actual drop wrapper and its visible
intersection, preserves genuine mouse/keyboard actions, distinguishes each
interaction stage, and adds only bounded failure DOM counts/visibility flags.
Dependency provenance is recorded in the fixture manifest and explained in its
[README](../integration/silex-export/README.md). Pins, deadlines, sandbox/network
scope, publication authority and manual editing requirements remain unchanged.

Source/inert checks cannot establish actual drag/drop or editing success. The
separately scoped Core test extension comparison correction and this Studio
candidate require independent review before another paired hosted trial. All
fifteen full Studio/hosting acceptance cases remain open.

Candidate source checks passed: 16 inert Python contract/parser tests (including
closed interaction receipt validation and rejection of private/invalid fields),
exact upstream archive SRI/lock/source-map hash checks, fixed selector/activation
source contracts, unchanged pin/config/deadline comparisons and whitespace checks.
The paired Core-only test correction passed standalone rustfmt/source checks.
No local Node/browser/Rust build or hosted rerun was executed for this candidate.
