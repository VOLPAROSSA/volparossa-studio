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
- Pending: independent source review, frozen dependency/build compatibility, actual
  sandboxed installed-Chrome/UI selectors, real export/Core decoder result and
  normal/failure/cancellation cleanup on one separately selected hosted trial.
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
The present evidence is source and inert parser/configuration checks. The hosted
fixture is implemented source awaiting execution; product integration acceptance
and the full requirements remain incomplete.
