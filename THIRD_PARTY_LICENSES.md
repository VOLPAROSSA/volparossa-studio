# Third-party source and license record

The initial documentation slice imported no third-party source or binary.
The integration records below identify later source inputs and transient tools.
The original root LICENSE remains byte-for-byte unchanged.

Selected Silex source: https://github.com/silexlabs/Silex,
v3.9.0 at `672efed69dda04c0a1e968859239e042f00d9538`.
[upstream.lock.json](upstream.lock.json) binds the inspected Git blobs.

| Component | Inspected notice | Primary source |
| --- | --- | --- |
| Editor and Node server | AGPL-3.0-or-later in file notices; package shorthand AGPL-3.0 | [publication source](https://github.com/silexlabs/Silex/blob/672efed69dda04c0a1e968859239e042f00d9538/server/api/publicationApi.ts), [LICENSE](https://github.com/silexlabs/Silex/blob/672efed69dda04c0a1e968859239e042f00d9538/LICENSE) |
| Rust silex-server | AGPL-3.0-or-later | [Cargo.toml](https://github.com/silexlabs/Silex/blob/672efed69dda04c0a1e968859239e042f00d9538/server-rust/Cargo.toml) |
| Tauri desktop wrapper | GPL-3.0-or-later | [package.json](https://github.com/silexlabs/Silex/blob/672efed69dda04c0a1e968859239e042f00d9538/desktop/package.json), [LICENSE](https://github.com/silexlabs/Silex/blob/672efed69dda04c0a1e968859239e042f00d9538/desktop/LICENSE) |

Preserve Silex Labs/contributor attribution and upstream notices unchanged when
integrating. Record every imported dependency, modified component and local patch.
Distribution and network-service source obligations need component-specific review;
the initial Studio GPLv3 file is not proof that an integrated AGPL implementation
satisfies its obligations. Assets/templates/fonts and generated site content need
separate ownership/license consideration. No compliance, build or runtime approval
is inferred from this initial source inventory. Later local patches are recorded
separately below and in the locked manifests.

## Optional hosted editor/export fixture inputs — 2026-10-22

The [fixture manifest](integration/silex-export/manifest.json) adds acquisition
provenance, without vendoring or modifying upstream code or relabeling its license.
Runtime source builds are pending independent review and hosted execution.

| Input | Exact source / integrity | License boundary |
| --- | --- | --- |
| Silex v3.9.0 | Above commit; SHA-256 of the original `pnpm-lock.yaml` in fixture manifest; app-only frozen installation with lifecycle scripts disabled | Existing AGPL/GPL notices remain unchanged. No Silex patch is selected; fixture config is independent VOLPAROSSA code. |
| Node 24.19.0 Linux x64 | [Official archive/checksums](https://nodejs.org/dist/v24.19.0/SHASUMS256.txt); archive SHA-256 and exact `bin/node`/`LICENSE` member hashes copied from Core's reviewed runtime pin and rechecked against primary checksums | Node MIT with its bundled third-party notices; exact upstream LICENSE is checked and retained with the transient runtime. |
| pnpm 10.34.4 | [Official package metadata](https://registry.npmjs.org/pnpm/10.34.4); tarball SHA-512 SRI in fixture manifest | MIT; complete package including original notices is acquired temporarily. |
| playwright-core 1.56.1 | [Official package metadata](https://registry.npmjs.org/playwright-core/1.56.1), [upstream tag](https://github.com/microsoft/playwright/tree/v1.56.1); exact version/SRI and frozen fixture lock | Apache-2.0; dependency manager preserves package license/notices. No Playwright browser binary is downloaded. |
| Installed hosted Google Chrome | Existing runner installation only; actual path, binary SHA-256 and version recorded at runtime, not an immutable pin | Proprietary Google Chrome runner prerequisite, not redistributed or a Studio product dependency. Absence fails the fixture. |

Only independently written fixture/configuration/test code is added under
GPL-3.0-only. Silex's unchanged upstream dependency lock includes additional
transitive components; a frozen install is not a complete dependency/license
security audit or distribution approval. Trial-generated sites contain only public
synthetic text/styles in this initial case, with no imported private assets.

## Rust server checks and compiler carrier — 2026-10-28

The server baseline checks the same pinned Silex source using its root Cargo
workspace and root lockfile. `cargo fetch --locked` acquires public registry
dependencies transiently; server library checks select `silex-server`, without
building the editor or desktop wrapper. This is not a complete dependency license
or security audit and grants no distribution or hosting approval.

Three GPL-3.0-only compiler-support files are copied unchanged from
[VOLPAROSSA Core](https://github.com/VOLPAROSSA/volparossa/tree/edf569300acbdf5e7715b5192ffbb293235b15ab/scripts)
at `edf569300acbdf5e7715b5192ffbb293235b15ab` into
`integration/silex-publication/toolchain/`. Their SPDX notices are retained.

| Core source | SHA-256 of the unchanged carrier |
| --- | --- |
| `scripts/provision-rust199.py` | `73183c57744925c962cfb2bd7414ac2c20df8848ddad20e6240ba3257a2f8fcd` |
| `scripts/rust199-components.json` | `5cf2439e109e9fa92a25037130a20f903282e703ddb0ce192d7c06a8ec2737ba` |
| `scripts/test-provision-rust199.py` | `7683044d41b47a1cd3bc488368f63c15973e54b4154fe834696def2b4a3903f3` |

The carrier authenticates the fixed Rust 1.99.1 manifest dated 2026-10-15,
component archives and installed payload before executable use. Official Rust
components retain their bundled MIT/Apache-2.0 and third-party notices in the
disposable runner installation; no compiler binary is committed or redistributed.
The selected version is a reproducible check input, not an upstream support,
MSRV or security-completion claim. Core's separate Rust 1.89 exception is not
applied to Silex's dependency graph.

## Local Silex publication patch — 2026-10-28

[The patch manifest](integration/silex-publication/manifest.json) binds eleven
changed paths in the pinned Silex Rust server/workspace, including the original
and resulting hashes and modes. [upstream.lock.json](upstream.lock.json) records
the patch and manifest hashes. The complete source patch is retained under
`integration/silex-publication/patches/`; no upstream checkout or binary is vendored.

The modified server and new Rust helpers/tests retain AGPL-3.0-or-later and the
original Silex notices. The independently written preparation driver/tests and
documentation are GPL-3.0-only. Keep both component licenses, corresponding source
and notices when distributing or serving this derivative; the Studio root license
does not relicense Silex. No publication, distribution or network-service compliance
approval follows from these source checks.

The only dependency membership change adds the existing locked `rustix` 1.1.3
package with its `fs` feature to the Linux server. All other root lock package
records and the historical server-local lock remain unchanged. The registry archive
checksum is `146c9e247ccc180c1f61615433868c99f3de3ae256a30a43b49f67c2d9171f34`.
[Its upstream manifest](https://github.com/bytecodealliance/rustix/blob/v1.1.3/Cargo.toml)
declares `Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT`; retain its COPYRIGHT
and LICENSE files with the acquired source and applicable distribution notices.
No package version update or complete transitive dependency audit is included.

## Native bootstrap overlay — 2026-10-29

The additive [native overlay manifest](integration/silex-native-bootstrap/manifest.json)
and its complete source patch bind five desktop paths after the preceding bounded
publication patch. Original Silex desktop GPL-3.0-or-later notices, its Rust package
AGPL-3.0-or-later declaration, embedded server notices and licenses remain unchanged.
No upstream checkout, SDK or application binary is committed. Independent drivers,
fixtures and documentation use GPL-3.0-only. The existing authenticated Node24.19.0
and Rust1.99.1 carriers remain separate transient tools with their original notices.

This source delta removes native install-ID/telemetry instrumentation, frontend SDK
injection and upstream Silex updater registration/key/feed. It removes their unused
direct dependency memberships. The authoritative root Cargo candidate removes44 obsolete registry records,
preserves all retained versions/sources/checksums and records three independently
reviewed feature reductions plus dependency-reference normalization. Its exact
before/after hashes are bound by the overlay manifest; the original failed strict
resolver report remains evidence. Offline locked verification, native
compile/runtime and general editor-plugin privacy acceptance are pending. Removal
of upstream updater authority does not fulfill the required independently
authorized VOLPAROSSA client updates, which remain open. No distribution, network
service, native publication-consent or full Studio approval is inferred.

### Dashboard input for the private native compile fixture

The fixture fetches Silex's existing `silex-dashboard-2026` gitlink at
`cb36b01a609915facfb1c134f96a98eabcdd3374` from
https://gitlab.com/silexlabs/silex_silex-dashboard-2026.git . Its nine public assets
are bound by `integration/silex-native-bootstrap/dashboard-source.json`. No
license file or explicit license declaration was observed at that commit; no
license is inferred here. The fixture does not upload its assets, compiled ELF
or generated frontend. Product redistribution remains unaccepted. Existing
upstream notices and the Silex project license records above remain preserved.

## Filesystem identifier and name-only overlay — 2026-10-29

The additive [FS manifest](integration/silex-fs-identifier-rename/manifest.json)
binds eleven paths after the exact Native6 overlay, including the complete patch,
before/after bytes, modes and hashes. The server derivative and its new Rust
helpers/tests retain AGPL-3.0-or-later; desktop MCP changes retain the existing
GPL-3.0-or-later notices. No component is relicensed. All Cargo manifests and root
and historical nested locks remain unchanged; no new dependency is introduced.
Independent preparation/proof drivers, tests and documentation use GPL-3.0-only.
Source review does not establish runtime, authorization, complete filesystem
confinement, native GUI, publication or redistribution acceptance.

The original local dashboard under `integration/silex-native-dashboard/app/` is
independently authored GPL-3.0-only HTML, CSS and JavaScript, with no framework or
borrowed dashboard assets. Its manifest records exact source bytes. A future
explicit native composition may embed only its three application files; unit
tests are separate. The existing nine-file GitLab dashboard fixture and its
unverified license remain a distinct private build input, unchanged. This
record does not grant distribution acceptance to a combined application.
