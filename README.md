# VOLPAROSSA Studio

A Silex-based visual website editor with shared VOLPAROSSA publishing, hosting
and AI assistance. The target is to create, preview, explicitly publish, update
and maintain portable websites using the cooperative DICN infrastructure.

**Development status:** source-audited Silex baseline and an implemented, unexecuted
[editor/export-to-Core hosted fixture](integration/silex-export/README.md).
Inert ZIP safety checks pass; no actual editor/build/export runtime, shared AI
workflow or decentralized website deployment has been verified yet.

The complete [permanent Studio/hosting amendment](https://github.com/VOLPAROSSA/volparossa/blob/main/docs/development/STUDIO_HOSTING_REQUIREMENTS.md)
is part of the [full VOLPAROSSA goal](https://github.com/VOLPAROSSA/volparossa/blob/main/docs/development/GOAL.md),
including its preserved original, every previous amendment and DPS. The
[hosting architecture and Core audit](https://github.com/VOLPAROSSA/volparossa/blob/main/docs/services/STUDIO_HOSTING.md)
and [local implementation status](docs/IMPLEMENTATION_STATUS.md) distinguish
existing foundations from work still required.

## Intended workflow

Create or import a site, edit visually or through authorized AI tools, preview
locally, validate the selected public assets, choose identity/hosting mode and
explicitly authorize publication. Core signs and delivers the publication;
Studio shows independently observed availability and replica health, and supports
authorized updates, rollback, recovery and withdrawal. Editing does not require
a deployed public site. Portable export and conventional hosting remain available
alternatives; useful dynamic hosting follows its own execution/state requirements.

Silex supplies visual design, responsive pages, HTML/CSS/JavaScript editing,
templates and accessibility features. Shared Core supplies networking, publishing,
Storage and protected Compute; Code's OpenCode integration supplies suitable agent
workflows. No second peer network, storage engine or AI scheduler is planned here.
Manual editing must work without AI. Private drafts, customer data, credentials,
photos and location metadata are never automatically published or used for training.

## Upstream and licenses

Initial adapter baseline: [Silex v3.9.0](https://github.com/silexlabs/Silex/tree/672efed69dda04c0a1e968859239e042f00d9538),
commit `672efed69dda04c0a1e968859239e042f00d9538`. [upstream.lock.json](upstream.lock.json)
records inspected files; this is not build/runtime or full dependency acceptance.
Prefer supported plugins, publication connectors and scoped MCP interfaces.

Silex is developed by Silex Labs and its contributors. Its editor/server components
carry AGPL-3.0-or-later notices; the desktop wrapper carries GPL-3.0-or-later notices.
The repository's existing [GPLv3 license](LICENSE) is unchanged and does not replace
upstream terms. See [third-party provenance](THIRD_PARTY_LICENSES.md). No Silex code
or binary is vendored. The opt-in fixture acquires exact upstream sources and
locked tools only on the approved disposable hosted runner.

Read [AGENTS.md](AGENTS.md) before development. Actual runtime trials belong on
approved disposable hosted runners, without modifying the developer's host.
