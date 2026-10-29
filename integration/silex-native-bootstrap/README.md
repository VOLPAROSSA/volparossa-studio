# Hosted desktop bridge regression checks

This finite Node builtin VM fixture executes the actual patched
`desktop/src-tauri/scripts/desktop-bridge.js`. It tests the retained project,
native-menu and MCP helper callbacks while refusing bootstrap telemetry. It adds
no npm dependency and performs no real network request, browser launch, native
Tauri execution, SDK load or external application launch.

Run only on an approved disposable GitHub-hosted Linux X64 runner, as its original
nonroot account, with the existing authenticated **Node 22.17.0** executable:

```sh
AUTH_NODE ABS_TEST_BRIDGE_MJS \
  --source-root ABS_PATCHED_SILEX_ROOT \
  --bridge-sha256 f51c34bb965e69ba7f907b2473b4aa310faef1fa98ba20003e49e6b8c824a482 \
  --baseline-bridge ABS_PRISTINE_BRIDGE
```

Use the script directly; builtin `node:test` emits TAP automatically. The fixed
argument order is required. Both sources must be canonical, owned regular
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
