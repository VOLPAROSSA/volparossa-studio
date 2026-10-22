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
Documentation/source checks are the present result, not implemented functionality.
