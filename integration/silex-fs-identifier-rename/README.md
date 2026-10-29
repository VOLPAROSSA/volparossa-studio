# Hosted FS identifier and rename proof

The explicit `native_followup=fs-identifier-rename` profile is restricted to the
`feature/native-local-dashboard-20261029` branch on the approved disposable
Ubuntu24.04 runner. It authenticates the existing Rust1.99.1 carrier, creates an
empty private Cargo home, and reuses the public-only locked acquisition of the
607-package / `35d0…3536` publication baseline. It then applies the reviewed
Native6 `e927…67bd2` overlay and the exact eleven-path FS descriptor and patch.
The existing preparation protocol tests run before compilation.

The source-bound `proof.py` verifies the full patched source, compiler payload
and 563-package / `de04…90118` root lock before full offline locked metadata and
the actual `cargo test --offline --locked -p silex-server --lib` suite. It requires
all fourteen reviewed FS case names, a unique complete suite, and zero failed,
ignored or filtered tests. The suite total comes from the actual result. Source
and compiler payload are checked again after execution. No SDK, frontend,
embedded assets, Node, browser or native desktop application is required.

The actual Cargo/test actor uses a private owned mode0600 combined log capped at
16MiB; success reads it through a stable bounded descriptor for the test summary.
Failure may project only the existing closed compiler codes/counts/flags and log
hash/size. Raw output is never printed or uploaded. The joined actor's log is
removed with the private tool/test tree before receipt publication; an unconfirmed
actor retains that private temporary tree and cannot pass.
Failures use finite stage/class projections. `operation_failure_kind` covers the
operation before terminal finalization; final cancellation/cleanup/publication
also gates the receipt status and cleanup fields, without inventing an operation
cause. The only artifact members are the
reused base-fetch receipt and `silex-fs-identifier-rename-proof.json`. Compiled
test output stays in a fresh private runner-temporary target, without binary
uploads. Owned process groups must join, and the private synthetic test tree
must be removed before success. The existing reviewed terminal receipt helper
keeps precommit cancellation fatal and makes only final receipt publication
noncancellable; no child or project action follows that boundary.

This is a hosted library-test candidate until exact-source execution succeeds.
Even success establishes only those actual Rust unit/HTTP-in-process/filesystem
cases. General path confinement, authorization, cross-process CAS, complete
atomicity, a running HTTP service, native GUI/privacy, publication, updates,
dependency acceptance and full Studio acceptance remain false. The earlier
private native build at `66f512c4` remains separate immutable evidence.
