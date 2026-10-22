# Third-party source and license record

No third-party source or binary is imported in the initial documentation slice.
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
is inferred from this source inventory. No local upstream patches exist yet.

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
