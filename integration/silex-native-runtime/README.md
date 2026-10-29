# Native runtime prerequisite inventory

This explicit hosted profile records nine fixed Ubuntu 24.04 package providers and ten runtime tools without executing those tools. It reads signed APT metadata, installed package state, package ownership and stable ELF bytes. Installed versions and candidate archive metadata remain separate. Binary hashes are observations, not independent archive-content verification. Missing prerequisites produce `readiness: not_ready`; a successful inventory is not runtime acceptance.

Run only through the manual `runtime-inventory` choice on `feature/native-bootstrap-runtime-20261029`. The job checks the exact source, updates signed system APT metadata, runs fourteen protocol/lifecycle controls, then writes one bounded JSON receipt. It installs no packages, downloads no archives, creates no namespaces, and starts no display, application, compiler or Node process. No native GUI, privacy, Debian 13, publication or full Studio acceptance follows.

The next runtime stage must separately establish the complete disposable isolation and cleanup contract before any native application starts. Existing private native compile evidence remains bound to source `66f512c444538127b7e59c34d5f618bb8a98d1cf`.
