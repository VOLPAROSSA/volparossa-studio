# Bounded Silex Rust publication preparation

This local AGPL patch targets Silex v3.9.0, exact source
`672efed69dda04c0a1e968859239e042f00d9538`. It changes Rust publication
preparation before connector selection, authentication, Storage reads or job
creation. It does not add a Core signing connector or publication authority.
The existing Node editor/export/viewer integration is unchanged.

`manifest.json` records the original and resulting hashes and modes for every
changed source, the patch hash, and the ROOT workspace lock. `server-rust` and
`desktop/src-tauri` belong to that workspace. The committed
`server-rust/Cargo.lock` is historical and remains unchanged; it is not the
selected build lock. The only root lock change adds the already locked rustix
1.1.3 package to silex-server's dependency membership. No package version,
checksum or other package record changes.

## Source preparation

Use a fresh owned checkout of the exact original source on an approved disposable
hosted runner. Never apply this patch to the retained source/recovery checkout.

```sh
python3 -B integration/silex-publication/prepare.py verify-baseline --source /absolute/pinned-silex
python3 -B integration/silex-publication/prepare.py apply --source /absolute/pinned-silex
python3 -B integration/silex-publication/prepare.py verify-patched --source /absolute/pinned-silex
```

Apply requires GitHub-hosted context, a clean exact checkout, the original lock,
and every original file binding. It checks the complete patch before mutation,
then verifies every changed byte and the single permitted dependency edge.
A failed operation is not a test result or successful publication. Its output
contains no project contents or credentials.

On the hosted runner, use the authenticated fixed toolchain and fresh public
Cargo home supplied by the independent workflow. Keep Cargo target output
outside the source checkout. Baseline and patched builds must use the same
compiler, lock source and command scope. No Tauri/browser/Node/SDK build is needed
for the selected library tests:

```sh
cargo test --locked -p silex-server --lib
```

Run the unchanged baseline first and preserve its failure if it cannot compile;
do not suppress or repair unrelated upstream failures to label this patch green.
The source/driver tests are separate:

```sh
python3 -B -m unittest discover -s integration/silex-publication -p 'test_*.py' -v
```

## Preparation contract

The original Axum JSON media-type requirement remains. A 256-MiB body limit is
applied before JSON deserialization, and the files deserializer retains at most
256 descriptors. Ignored outer editor metadata remains compatible. All paths,
source references, duplicate names, query identifiers, index presence and inline
byte totals are checked before any connector lookup or read.

Normal `index.html`, `css/style.css` and canonical `/index.html` output paths map
to Core's absolute asset profile. Paths are at most 1,024 UTF-8 bytes. Empty/dot
components, hidden components, traversal, percent-encoded aliases, backslashes,
queries, fragments, whitespace/control characters and colon aliases fail closed.

Stored references accept a relative asset name, `/assets/name`, or the documented
`/api/website/assets/name` route. Full HTTP(S) references must use the exact
operator-configured origin without a path/userinfo component; another origin is
never silently reinterpreted as a local asset. Query-bearing API references must
bind the selected website. A connector query additionally requires that exact
explicit Storage selection. No supplied URL is fetched. Empty Storage IDs,
ambiguous aliases and unsupported query parameters are rejected.

Before any asset read, reserve the four-byte Core framing prefix and a proved
upper bound on its protobuf index: version field, each nested Entry tag/length,
exact path length, MIME up to 128 bytes, and ten-byte u64 offset/length varints.
The index may not exceed 256 KiB. Inline bytes and every subsequent stored asset
consume the same remaining 256-MiB whole-object budget. Conservative reservation
can reject a revision near the exact codec limit; it never enlarges that limit.
The actual Core codec and review/signing requirements remain independent.

One original 30-second preparation deadline covers validation, session/auth and
all materialized assets; a later asset receives the same deadline. Preparation
failure or cancellation cannot reach the later hosting/job step.

## Filesystem capability and lifecycle limits

`StorageConnector::read_asset_bounded` defaults to an explicit unsupported error;
it never calls the old unbounded method. Only FsStorage implements it here.
Ordinary Storage operations and authentication semantics remain unchanged.

On Linux, safe rustix openat2 operations refuse symlinks/magic links and resolve
website/assets/file paths beneath owned directory descriptors. The website ID
must be one bounded relative component; the operator's asset folder may contain
safe relative components. This is path containment, not proof of user ownership
or publication consent. Existing FsStorage's always-logged-in local behavior,
other read/write APIs and FsHosting's publication writes are outside this patch.

All opening, metadata inspection and file reading occurs in bounded blocking
jobs, with two shared permits per FsStorage. Regular single-link file metadata is
checked before allocation. Reads allocate only the observed bounded length and
check one additional stack byte for growth; truncation or observed metadata
changes reject the result. This is not an atomic filesystem snapshot guarantee.

The job checks cancellation and the original deadline before/after read chunks.
A cancelled or timed-out caller sets a cooperative cancellation flag; its job
keeps the permit, descriptor and allocation capacity until it actually stops.
A kernel-stalled filesystem operation cannot be forcibly interrupted here.
Outstanding resources stay limited, but dropping the caller does not prove the
worker joined or that whole-connector shutdown drained. Non-Linux platforms
report this capability unsupported; there is no unsafe fallback.

## Evidence and licensing

Rust tests cover the actual Axum handler ordering, JSON body/media-type gates,
inline and bounded filesystem revisions, default capability refusal, resource
geometry, partial failures, source aliases, file mutation/path containment,
one shared deadline and cancelled-worker capacity retention. Their execution and
compiler compatibility remain unverified until the hosted run passes.

The patch modifies and extends AGPL-3.0-or-later Silex Rust code. Original Silex
copyright/license notices remain intact; new Rust helpers/tests retain AGPL terms.
The independent Python driver/tests are GPL-3.0-only. Preserve the upstream root
and server-rust LICENSE files, patch provenance and corresponding-source notices
when distributing this derivative. Studio's root GPL license alone does not
relicense the patched Rust component.

No result here establishes native publication authorization, independent hosting,
browser rendering, publisher-offline availability, confidential processing,
dynamic execution or complete Studio acceptance.
