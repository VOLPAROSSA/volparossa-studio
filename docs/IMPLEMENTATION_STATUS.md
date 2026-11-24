# Studio implementation status

Updated 2026-11-24. Requirements are the complete permanent
[Studio/hosting amendment](https://github.com/VOLPAROSSA/volparossa/blob/main/docs/development/GOAL.md#studio),
incorporated by the full Core goal. This file records Studio evidence and next
work, without replacing that scope or the shared Core execution ledger.

## Five native assets signed and recovered on the producer

Two fresh Silex desktop processes reopened a two-page project containing edited
text and an imported 1024 × 768 chart. File system hosting exported five files
whose bytes matched the Silex Download export. Core `6924fe8b` packed the
native files into 2,358,929 bytes across nine chunks. The synthetic owner
selected the reviewed SHA-256 before signing. An independent local browser
opened the recovered signed site, checked all five assets and rendered the
edited text at 37 px. The resulting bundle SHA-256 was
`4cae1917f2f197d608d4df699d910384506d7f418007473825849da002909e2d`.
[Producer on Studio `8d6f20f7`](https://github.com/VOLPAROSSA/volparossa-studio/actions/runs/45425108548) · [Original producer receipt](evidence/native-webview/45425108548/studio-export-receipt.json)

The [native trial index](evidence/native-webview/runs.json) binds the producer
and six preceding attempts to their original archive digests. The index links
the native and editor reports generated before each attempt stopped. The
[package-index attempt](https://github.com/VOLPAROSSA/volparossa-studio/actions/runs/45408283487)
stopped during the Core CLI build, after the SDK installation.

## Native editor export to Core — 2026-11-19

The native Silex dashboard created a filesystem-backed project. The fixture
saved a heading containing its new project ID through the local API. Two fresh
WebKit editor processes opened that project and displayed the saved heading.
In the second editor, Alt+P and Publish selected Silex's File system hosting
connector. It wrote `index.html` (411 bytes) and the stylesheet referenced by
that page (156 bytes) into the project's local publication directory.
[Native trial at Studio b0f77d2](https://github.com/VOLPAROSSA/volparossa-studio/actions/runs/44553636524)

Core `c8689558` packed that directory into a 701-byte site bundle. Its SHA-256
was `1991c962faf8c12ef65863a06ff5a6504ef2c6d7240bc5ff65a558d8973abbe2`.
The trial compared the original files before and after packing, checked both
hashes against Core's asset inventory and hashed the actual bundle. The Core
receipt requires owner review and reports unsigned local preparation. All four
GUI process groups exited and the runner restored its initial network state.
The manual `native-site-export` workflow runs on protected `main`.
[Original reports](evidence/native-webview/44553636524/)
· [Owner workflow](../integration/silex-native-runtime/README.md#prepare-the-native-editors-local-output-for-core)

Protected `main` at `175360cd` repeated the entire native export with a new
project ID. Its page and stylesheet had the same lengths and new content hashes.
Core created a 701-byte bundle with SHA-256
`94f024685abeafd7d44788a385b6a5494e1bc49df77ccb905d5b76689a301149` and required
owner review. Both native windows displayed the saved heading and quit normally.
The runner saw 278 loopback request packets and 258 response packets and restored
its original network state. The eight-report archive was 41,865 bytes with
SHA-256 `f88420d4ae6ff0117ff6547af7aa1311bb1d242057cda9885892be15d40706b5`.
[Protected native export](https://github.com/VOLPAROSSA/volparossa-studio/actions/runs/44558150491)
· [Original protected reports](evidence/native-webview/44558150491/)

The independent Firefox hosting trial below used a separate five-asset site.
Owner authorization, signing and independent retrieval during a publisher
outage remain to be demonstrated together for this native export.

## Native Silex desktop reopens a saved canvas — 2026-11-19

The original Silex v3.9.0 desktop at `672efed69dda04c0a1e968859239e042f00d9538`
ran from an offline Rust 1.99.1 build with the local Studio dashboard. The
Azure runner used Ubuntu kernel `7.0.0-1017-azure`. Its 184 pinned SDK packages
accounted for 74,345,024 bytes. The frontend contained 54 assets. The resulting
34,339,248-byte ELF had SHA-256 `c0e61387d81728b79f13dd05266893d9d601f98b6338e484d7a13a0277c060b9`.
[Hosted run at Studio source 44edad8](https://github.com/VOLPAROSSA/volparossa-studio/actions/runs/44542272228)
· [Original build receipt](evidence/native-webview/44542272228/silex-original-dashboard-build.json)

The unprivileged desktop opened to an empty project list. The native pointer
and keyboard submitted the dashboard form. Silex created a filesystem-backed
project and assigned its ID. The fixture saved a heading containing that ID
through the local API. In each of two fresh desktop processes, the dashboard's
Open action reached the named editor, a real WebKit web process ran, and the
visible canvas exposed the exact heading through accessibility. Both windows
showed the clean project title. Both quit through Silex's own Quit dialog, exited
with code zero and stopped their local servers.
[Original native receipt](evidence/native-webview/44542272228/silex-native-webview.json)

The two launches added 261 loopback request packets and 242 response packets.
DNS and blocked IPv4/IPv6 counts stayed at their pre-launch calibration values.
All four GUI process groups joined, the namespace exited and the kernel module
returned to its initial state. Host routes, resolver and firewall matched their
initial snapshots. The original seven-file archive was 40,934 bytes with SHA-256
`1a09fa8bc81fd173473cfa3fff150a2858f2fb574be1e86d1b574383de3ec1fa`.
The manual `native-webview` profile runs on protected `main`. The archive index
also retains the preceding observations, including the first visible canvas and
the first double reopen observed before the test helper's shutdown was corrected.
[Receipt index and file hashes](evidence/native-webview/runs.json)
· [Ubuntu kernel module provenance](evidence/native-webview/ubuntu-veth.json)

A fresh run on protected `main` at `7e09c9ba` repeated the complete native
workflow with another project ID. Both native canvases exposed their saved heading
and both processes exited normally via Quit. The original seven reports record
250 loopback request packets and 237 response packets, unchanged external counters
and complete host cleanup. The 40,936-byte archive has SHA-256
`57a72de3465e7c470e4161d08691b991507d3300ea8bd5c0df507345bb7a4fbb`.
[Protected run](https://github.com/VOLPAROSSA/volparossa-studio/actions/runs/44547586924)
· [Original protected reports](evidence/native-webview/44547586924/)

## A fresh browser opens a Studio site after its publisher goes offline — 2026-11-18

A single hosted trial followed a synthetic public site from its saved Silex
project to an independent Firefox reader. The exact revisions were Studio
`cb66fd7f35b7bda3012b771d2a136fb9fa836fc1`, Core
`2069691283cb5b84152e3b551a7430fc53796500` and Silex v3.9.0
`672efed69dda04c0a1e968859239e042f00d9538`.
[Successful run 44384131952](https://github.com/VOLPAROSSA/volparossa/actions/runs/44384131952)

The editor reopened the saved page with its imported 1024 × 768 chart and
exported five assets. Core signed the 2,358,929-byte bundle, recovered it
locally after an agent crash and verified its original bytes. The same
runner handed the bundle and signed manifest privately to the Debian 13
VM. The first provider served the original publication. A second peer
fetched it by publisher and name over protected MPTCP, retained all nine
chunks, then removed its acquisition cache and temporary output.

The fresh client's viewer retrieved all 2,358,929 bytes from the second peer
while the first provider's service, PID and listener were absent. It verified
every asset hash, a 4,096-byte range of the chart and the HTTP security headers.
The origin supplied zero bytes. In that client namespace Firefox ESR 140.16.0
displayed the edited text at 37 px and decoded the chart. The browser, profile,
listener and owned topology objects were cleaned up. The disposable guest's
root-network state matched its initial snapshot, and the outer runner joined
QEMU and removed the private guest state.

| Evidence | SHA-256 |
| --- | --- |
| Signed bundle | `7a8ca0a33db9854bda2045777b1ce2d6890e5bb150d72e6839e3261d099ccc1e` |
| Original signed manifest | `7e10133bdf41abaefa0f221dac7dcd926848abe40198803c19c9a6b91e072257` |
| Producer archive 14465988826 | `c535ff02feba5cb5253c3d8d3f15823c2a9b4fbce7ced99e0cb214aa945d70e1` |
| Independent hosting archive 14465324138 | `45798c872937e4843e2f29e03f87511e031b39546d4c311059ae49187e7c4a2b` |
| Independent hosting report inside that archive | `883e202ff854c6d63ddc2c7779e40b4bea885b21aee66ed9e357be5a1c6b67a5` |

The preceding attempt used Core `910d8631a50b011d1a181385ceccf7d75c60dfc0`
with the same Studio revision. It passed 31 site tests and nine signed-recovery
tests, then stopped at strict Clippy on the length of a contribution test.
Runtime editor and VM verification began in the successful follow-up.
[Original run 44382248754](https://github.com/VOLPAROSSA/volparossa/actions/runs/44382248754)

Availability here depended on a reachable holder retaining every chunk and on
the original publication still being valid. Public DNS/TLS, long-term hosting,
release consent, rollback, withdrawal and dynamic site execution have separate
acceptance requirements.

## Save and reopen a project — 2026-11-18

[Run 44366437457](https://github.com/VOLPAROSSA/volparossa/actions/runs/44366437457)
reached the acknowledged filesystem save and succeeded in the original editor
preview. The fresh editor opened, then timed out during reopen verification.
The receipt reports a visible empty canvas, zero failed requests and successful
cleanup. The follow-up checks the reconstructed page in the filesystem read,
selects it by Silex's keyboard shortcut and confirms its name in the toolbar
before checking the restored text and font size. The original timeout does
not identify which part of the combined reopen observation failed.

[Run 44368192079](https://github.com/VOLPAROSSA/volparossa/actions/runs/44368192079)
passes with Studio `db6cae985daa`, Core `9b8f92ed9572` and pinned Silex
`672efed69dda`. Chromium reopened the saved page in a fresh context and
verified its text and 37px styling. The export from that reopened editor
produced a 1,474-byte ZIP. Core verified all four assets, the edited HTML and
CSS, and rejection of overwrites. The fixture drained its processes and
removed its temporary files. Receipt archive `14457193442` has SHA-256
`d632130b6ac8b6be2b8e28d6655720f88c8b8d1d086a938f6c488af377655bd9`.

## Local signed-site recovery — 2026-11-18

On Studio `2c5e414507d9` and Core `7208e241af8f`, the reopened Silex editor
exported a 1,478-byte ZIP. The real CLI packed and signed a four-asset,
1,204-byte bundle with an ephemeral test identity. An agent with networking
roles disabled imported it. After a forced process crash, its replacement
reopened the same cache and exported the identical bundle. An independent
Chromium instance rendered the edited text at 37px and verified all four
assets and the preview's security headers. Six successful CLI operations,
two rejected operations and both agent instances were joined. The browser,
listener and private state were cleaned up. The later joined trial above covers
independent peer retrieval during the publication lifetime. Public network release,
power-loss recovery and native publication consent require separate evidence. Receipt archive `14458047882` has SHA-256
`aa1d1d4c845f86aa36e363d6ea1c2375abcdde76883196cc41708910f2edcd68`.
[Hosted signed-recovery run 44368339229](https://github.com/VOLPAROSSA/volparossa/actions/runs/44368339229)

## Ordinary source CI and dependency updates — 2026-10-27

The proposed `Studio CI` workflow runs the stable `source-contracts` job on
ordinary pull requests and pushes to `main`, without path filters or actor
exclusions. It uses a disposable Ubuntu hosted runner, read-only repository
permissions and SHA-pinned checkout without persisted credentials. It needs no
secrets, dependency installation, Core checkout, browser, SDK or native build.

Run the same 37 existing checks locally from `integration/silex-export`:

```sh
python3 -B -m unittest -v test_contract test_lifecycle test_runtime_context
```

These cover Python syntax, synthetic extraction/diagnostic contracts, bounded
process cleanup and private context handoff. `test_wrapper_guard.py` requires
Core's namespace wrapper and remains in the separate Core integration trial.
Source checks do not accept the Studio application or hosting platform.

Dependabot proposes weekly Monday updates for npm/pnpm in
`/integration/silex-export` and GitHub Actions in `/`, with at most three open
version-update PRs per ecosystem and grouped security updates. Existing exact
dependency/package-manager pins, lockfile and Silex provenance stay unchanged.
Future updates must reconcile the fixture manifest/provenance contracts and
retain exact dependency versions and full Action commit SHAs before merge.

F06/F10 remain proposed until manual merge and a fresh check on `main`.
The existing branch ruleset is unchanged; `source-contracts` is not required.
Fork/Dependabot execution and failed-check merge blocking need separate evidence
before an explicitly approved ruleset change.

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

## Current bounded export and Core-pack acceptance — 2026-10-23

Actual hosted run `39869460125` succeeds on Core
`dfa6f3434bb9f7fe07c4fff2bacfc0042780faa7` and Studio
`eaf9e336e003b7cab8f384271560b182aee464ae`, with pinned Silex
`672efed69dda04c0a1e968859239e042f00d9538` unchanged. The real browser created
a page, edited text and 37px styling, previewed it, and downloaded an actual
1,477-byte ZIP. The actual Core CLI and production `SiteBundle` decoder then
verified all four assets, hashes, lengths, HTML/CSS marker content and rejection
of overwrite. This accepts bounded browser edit/preview/export and offline Core
pack/decode for this fixture.

Independent High review confirms page-model serialization, not saved-project
reload or durability. Forty-four focused checks pass. Owned fixture and temporary
cleanup reports success; a full host-absence audit was not performed. Artifact
`12465313602` is 929 bytes, SHA-256
`240587795f7f55b11e5cadc6e3fcf2bdcec1f93804ae635069c47bdb9804776c`; raw job log
is 119,355 bytes, SHA-256
`1e8949cd247faed208e1c364aa8b3e478bfeae8655645da577a0e640bbf93d22`, retained
under Core `.git/ci-evidence/studio-export-39869460125/`.

Core PR330 is merged as `18b96ff3ab5021c6974278433651ce1bfbf28017`, tree
`b18c489730cb32c56b3e7bbbdb6fcb80ffa5533a`; composition was inspected, with
post-merge checks recorded separately. Studio PR2 is merged as
`bb89a781d56ff4a26d6babb624b7704a72cf9134` with exact tree
`789143a59ebe03dec13486061f6e3a2bc3fefce3`.

This bounded result does not close any of the fifteen complete acceptance cases.
There is no acceptance for saved-project reload/durability, signing, network
publication, independent hosting, shared AI, dynamic execution or a desktop
publication adapter. The next publishing work is untrusted export preparation,
separate trusted native review, offline Core signing, and separately authorized
contribution. The editor/MCP window cannot authorize signing. Core expected-
publisher guard PR337 is merged as `b1555912`; its actual CLI tests pass, but no
native adapter or end-to-end publication authority is implemented.

## Implementation and acceptance still required

### Export-to-Core fixture candidate — 2026-10-22 (historical pre-acceptance snapshot)

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
- At this historical candidate checkpoint after the first failed hosted trial:
  independent review of the narrow
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
- A future passing narrow receipt at this historical checkpoint was expected to
  prove synthetic local editor/export/offline packaging only. All fifteen complete
  acceptance cases remain open; no signing,
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

All fifteen complete cases in amendment section 8 remain open for this integration.
The bounded fixture acceptance above supplies evidence for part of edit/preview
and portable export, but does not satisfy those cases' full criteria:
create/import; edit/preview; explicit authorization; Core signed publication;
independent complete browser rendering; documented publisher-offline availability;
atomic updates; rejection of unauthorized/stale/forged revisions; failed-deployment
continuity; resource fairness; real shared-AI editing; independent pre-publication
review/tests; private data protection; portable export; recovery/withdrawal/cleanup.
Useful dynamic forms/APIs, server execution and durable application state have
separate Compute/Storage/availability requirements. No global uptime, censorship
resistance, public HTTPS or confidential execution claim is established.

## Active execution order

1. Build the native desktop publication adapter: untrusted export preparation,
   separate trusted native review, offline Core signing and separately authorized
   contribution. Never authorize signing from the editor or MCP window.
2. Exercise real editor, publisher, independent identities/peers and browser rendering;
   prove complete asset retrieval after the publisher goes offline under stated bounds.
3. Complete updates/retention repair/rollback/withdrawal and honest availability status;
   retain original expiry, anti-replay floors and participant resource budgets.
4. Integrate shared Core AI and Code/OpenCode through permission-scoped supported MCP
   tools, private processing protections and independently reviewed changes.
5. Add useful Browser/Cloud/Code/Image/Mail/DPS/Map/other application paths; extend
   dynamic hosting when authorized execution and durable state are ready.

This order is adaptable. Existing critical Core Storage, protected Compute, network
and DPS integrations stay active and must not be discarded or needlessly restarted.
Do not install Silex or change the development host to satisfy these acceptance cases.
Current evidence includes the bounded successful fixture above and the retained
failed trials below. Full Studio/hosting acceptance remains incomplete.

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

### Fourth hosted export trial — drag returned, insertion unverified

[Run 39853696060](https://github.com/VOLPAROSSA/volparossa/actions/runs/39853696060)
bound Studio `da7c5cd10fae2e57666fc7f826c2493ed1bae0f3` and Core
`4458ea4d2e15c5c1d7d812a4cfaa34fe70da4c19`. It failed `manual_text_ready` with
`TimeoutError` after the real drag returned. Failure DOM counts were blocks 14,
Text blocks 1, frames 1, wrappers 1/visible, fixture text 0, editable fixture text 0;
startup error counts were zero. All reported cleanup passed. Component insertion,
manual text/style editing, preview, export and actual Core packaging are unverified.
Original artifact `12458772476`, 1013 bytes, SHA-256
`07c36bc9add2888752fb49a8e8adacf8fb56beace0464c53e460d986ea7be4fb`,
is retained under Core `.git/ci-evidence/studio-export-39853696060/`.

Source tracing establishes Chrome's native HTML5 path, the block's intentional
mouse-sorter bypass, native dragstart/source initialization and wrapper native
enter/over/drop handling. Pinned Playwright already forwards native drag events
for ordinary mouse moves; swapping gesture helpers would not establish a fix.
The failure has no drag-event or hit-test evidence, so its cause remains unknown.
The diagnostic-only candidate preserves the gesture, selectors, pins, deadlines,
sandbox, network/publication authority and all success criteria.

The candidate adds fixed pre-input/post-mouse-up hit-test/native-draggable
booleans, explicit observation statuses and five trusted native event counters
capped at 32. No payload, raw DOM/error text, coordinates, identifiers or project
data cross the diagnostic boundary. Listeners do not modify input flow or DOM;
normal, partial-setup and failed-input paths detach them. Late failure capture
returns stored phases inside the same existing budget, without relabeling a late
sample as post-drag. Closed controller validation rejects unknown/private fields,
invalid types/statuses and unbounded counters. Source hashes and provenance are
recorded in the manifest; see the fixture [README](../integration/silex-export/README.md).
Independent review remains required before a new hosted trial. This source/inert
candidate supplies no new editor/export or complete Studio acceptance evidence.

Candidate checks passed: 20 inert Python contract/parser tests, including closed
pre/post drag schema/privacy/bounds checks, receipt validation and a source guard
against payload reads or input-flow changes. Source checks verified exact native
path archive/SRI/source hashes and license retention, identical mouse gesture and
timeouts, unchanged runtime/config/dependency pins and whitespace. No local
Node/browser/native build or runtime trial was executed; JavaScript behavior and
actual trusted-event delivery remain unverified until the reviewed hosted trial.
