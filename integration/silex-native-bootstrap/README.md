# Hosted desktop bridge regression checks

This finite Node builtin VM fixture executes the actual patched
`desktop/src-tauri/scripts/desktop-bridge.js`. It tests the retained project,
native-menu and MCP helper callbacks while refusing bootstrap telemetry. It adds
no npm dependency and performs no real network request, browser launch, native
Tauri execution, SDK load or external application launch.

Run only on an approved disposable GitHub-hosted Linux X64 runner, as its original
nonroot account, with the existing authenticated **Node 24.19.0** executable:

```sh
AUTH_NODE --test-reporter=tap ABS_TEST_BRIDGE_MJS \
  --source-root ABS_PATCHED_SILEX_ROOT \
  --bridge-sha256 f51c34bb965e69ba7f907b2473b4aa310faef1fa98ba20003e49e6b8c824a482 \
  --baseline-bridge ABS_PRISTINE_BRIDGE
```

Use the script directly with the explicit TAP reporter; the owning Python
`check_bridge.py` caller supplies this flag and checks every case and total. The
fixed script argument order is required. Both sources must be canonical, owned regular
single-link files under `GITHUB_WORKSPACE` or `RUNNER_TEMP`, without group/world
write permission. One descriptor supplies bounded bytes and stable before/after
metadata. Each source is capped at 64 KiB and SHA-256 checked before execution.
There are nine tests, each with a five-second test deadline and a 200 ms bound on
every VM evaluation, including its context-owned Promise microtasks. Apply the
owning workflow's outer process/job timeout too; this is not a native cleanup test.

Before applying the overlay, the owning driver retains the pristine bridge from
the exact upstream source:

```sh
git show 672efed69dda04c0a1e968859239e042f00d9538:desktop/src-tauri/scripts/desktop-bridge.js
```

Write that output into the private hosted temporary tree. Its required digest is
`f91e9debbe5a67175ce93bdcd17c29b8b13ba1ae5616ffa450bea4d315d90fa3`.
The positive control executes those real pristine bytes against the same stubs
and detects the stale native telemetry context, SDK insertion, install-ID handoff,
listener-error reporting and project open/save/publish timing. This prevents an
inert or incomplete mock from making the privacy assertions pass vacuously.

Patched-source cases retain dashboard reset, project metadata/fallback, dirty
tracking, all four native-menu callbacks, local/external link routing, editor
polling, component lookup, selection, capability discovery, fallback states and
delegated data-source helpers. The stale telemetry response remains available in
the mock, while a throwing Sentry property and SDK-insertion refusal detect any
attempt to use it. Unexpected fetches/native commands fail closed. All fixture
values are explicitly public synthetic values; no real identity or project is
opened.

The VM is a behavior fixture, not a security sandbox for arbitrary code. Exact
source hashes are mandatory. Green VM tests establish only these bridge behavior
and bootstrap boundaries. They do not establish GTK/WebView runtime behavior,
whole-application log privacy, arbitrary imported-page SDK absence, human consent,
native signing/publication, hosting, or full Studio acceptance. Existing debug
logging and the OS-link bridge remain in scope as retained functionality, not as
privacy acceptance. Core's separately required independently authorized automatic
updates remain open; removal of Silex upstream updater authority does not satisfy
that requirement.

All execution belongs to hosted evidence. No local Node/test/native execution is
needed to inspect these source files.

## Offline lock resolution

The historical source at `6a7406f` used the opt-in `native_followup=resolve-lock` profile authenticates the existing
Rust1.99.1 compiler carrier and acquires the exact607-package base-lock sources into
a fresh private Cargo home before applying this native overlay. The first network
fetch uses the same explicit environment and preflight configuration/credential
refusal as the resolver, through its fixed `--fetch-base` mode. It then resolves
metadata offline and requires a second offline locked query. A fixed target-cache
location under the runner temporary directory keeps generated metadata out of the
source tree. No GTK package is installed and no application is compiled or run.

The original lock, result lock and closed receipt are retained for independent
review. Retained package records must stay identical, including version, source,
checksum and dependencies. Only the five removed desktop memberships may change;
unused registry records may disappear. Unexpected changes fail closed. This is a
lock candidate, not native build, runtime, publication, update or full Studio
acceptance. The final six-path overlay must apply its lock delta after the existing
bounded-publication lock (`35d0…`), rather than against the original upstream lock.

## Exact reviewed lock candidate

The first resolver run40807343802 correctly failed its strict retained-record rule.
The original and candidate locks remain separate evidence. Independent review
accepts only the exact candidate SHA256
`de04aaf5ff1acbdde421e3447ea67f3eb7a00a7d5ed118f4387a180e84590118`
for the additive six-file source overlay, after the base lock SHA256
`35d0ea429b62f5cd2bc8533f75f997c05e787ad3355a40c1de0eba5fd3233536`.

The607→563 record delta adds no package identity and changes no retained version,
source or checksum. Dependency spelling/order normalizations preserve their
concrete targets. The desktop loses its five memberships. Three additional
feature reductions follow the removed updater/Sentry dependency closures:
libredox loses redox_syscall0.7.1; rustls loses the ring edge; objc2-ui-kit loses
nine optional framework edges. This is not an assertion that only the desktop
dependency record changed, and the generic resolver's failed result is retained.

The separate exact-candidate offline locked query and unchanged-source verification
passed in run40809750188 on Studio d64b6731ea3e54aa84e0b1cd00da50658667e8de.
Both base-fetch and verification receipts report nine direct children joined.
Native build/runtime remain required. The source overlay manifest continues
to mark those acceptance boundaries false. Original component licenses and
notices remain unchanged; no SDK or application binary is committed.

The current `native_followup=verify-lock` profile selects only the exact reviewed
candidate in the six-path overlay and performs an actual full offline locked
query plus unchanged-source checks. It does not reinterpret the historical
resolver failure as success or allow arbitrary dependency changes.

## SDK acquisition and disposable installation

The fetch-only profile passed in [run40810185163](https://github.com/VOLPAROSSA/volparossa-studio/actions/runs/40810185163)
on Studio `f5dce206a4da22b90ba83a2f0e4f054e42f900df`: twelve controls and
182 actual archives, totaling 63,772,228 bytes. Every archive name, version,
architecture, length and SHA-256 matched `ubuntu-sdk.json`. Three owned process
groups joined; the private archives stayed on that disposable runner. The artifact
contains only the receipt, never SDK archives. No installation, extraction or
native application execution occurred.

The original [run40809752563](https://github.com/VOLPAROSSA/volparossa-studio/actions/runs/40809752563)
failed before download because the mirror descriptor contained two previously
unobserved Ubuntu fallbacks. The correction binds the exact observed 144 bytes,
including ordering and priorities, to SHA-256
`e0d6b0af979e4662d16357a27ae456cc6f21e26da031540f4df8706ebed1d583`.
HTTP and HTTPS redirects stay disabled. No wildcard host admission or package-pin
change was made, and the first failure remains retained evidence.

The explicit `sdk-install` profile is a separate, unverified candidate. It first
reacquires the same verified archives in that job, then admits only the frozen
closure to offline installation on an approved disposable hosted runner. It
never authorizes development-host changes, GUI execution, publication, release
or mandatory Core update acceptance. Its bounded privileged helper and receipt
require independent review and a real hosted result before installation claims.

The installation helper uses a separate network namespace with no usable route,
a root-owned copy of each verified archive and fixed APT arguments
`--no-remove --no-download --no-install-recommends`. It simulates the exact
closure, rejects downgrades with dpkg version ordering and checks every installed
version plus `dpkg --audit` afterward. A newly created service-start denial policy
is removed only after the owned privileged process groups have stopped; an
existing policy is preserved by refusing the trial. Root and outer receipts keep
failed or unconfirmed cleanup visible. No rollback of an interrupted disposable
runner package transaction is claimed.

The first installation [run40812264217](https://github.com/VOLPAROSSA/volparossa-studio/actions/runs/40812264217)
on `3b40eaa3394400f5dd3ac27e80ede87d9952ed9f` passed both sets of twelve controls,
including the real harmless TERM-resistant descendant, then reverified all SDK
archives. The privileged helper refused admission before archive staging or APT.
The original failed root/outer receipts remain separate evidence; no SDK install
acceptance follows from the controls.

The explicit `sdk-admission` profile reads the identical privileged predicates
with finite phase diagnostics. It performs no package-index update, download,
archive access, cache creation, policy creation or installation. Its separate
root/outer receipts keep every installation and native acceptance flag false.
Only this bounded diagnostic is selected while the first refusal is investigated.

The shape-only follow-up [run40814124602](https://github.com/VOLPAROSSA/volparossa-studio/actions/runs/40814124602)
on `821d1e6f73802127fccf54e782533d5317d8c6d8` passed sixteen controls and
confirmed the causal input: the fresh namespace returned exactly zero bytes
for its IPv4 route file. The previous one-header-line check rejected that empty
form. The local parser now accepts only the observed empty byte string or one
known header line; whitespace-only data, unknown lines, extra headers and route
entries are refused. Other namespace, source, SDK and installation guards stay
unchanged. The next normal installation result remains required.
