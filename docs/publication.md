# Private GHCR publication gates

Selected registry: private GitHub Container Registry, under `Chiv2-Community`.
Forgejo and public packages are not publication targets. No release workflow
currently pushes images.

## Required before licensed image upload

- Approve Epic, SDK/game-content, compiler, and base-image redistribution terms
  and the exact eligible download audience. Registry authentication alone does
  not establish recipient eligibility.
- Use separate Windows and Linux package names. Record the Windows base/kernel
  compatibility requirements; do not advertise an unvalidated combined manifest.
- Establish private package permissions explicitly, including inherited
  repository access and Actions access. A private Git repository is not proof
  of private package access. If a new package needs a permission probe, use only
  engine-free content until its permissions are verified.
- Limit upload credentials to the trusted build/release job. Do not enable
  package writes, licensed remote caches, or self-hosted runners for untrusted
  PRs. Do not expand a developer token's scopes automatically.
- Pass the respective image's source cook, package integrity, and runtime gates.
  Local engine compilation and engine-free unit tests are not sufficient.

## Candidate and supported-release checks

1. Upload only to an approved private candidate package/tag; record its digest.
2. From a fresh compatible runner in a separate approved consumer repository,
   authenticate with read-only credentials and pull the digest.
3. Run the generic source-to-PAK build and retain its input/toolchain manifest.
4. Verify anonymous pulls and an authenticated, unapproved consumer are denied.
   A denied package-list API request is not a download access-control test.
5. Run the external workload comparison and Windows-game validation against the
   pulled digest. Promote only those tested bytes; record both OS digests and
   evidence links in the release.

Never overwrite a released version tag. If publication is interrupted, retain
the candidate as unsupported and retry with a new candidate identifier. Roll
back consumers by selecting a previously validated digest, not by retagging.

Before promotion, inspect image history, logs, provenance, filesystem layers,
and cache configuration for credentials. SDK/engine sources and caches remain
restricted even when no credentials are present.

## Current blockers

- No verified Windows container build or Linux-hosted Windows-target cook.
  Native hosted Windows source cooking passes.
- No approved recipient list or completed redistribution review.
- No package permission or separate-consumer pull tests.
- The current host GitHub credential cannot list organization packages
  (`read:packages` missing). This is not evidence about package visibility.
  Arrange appropriately scoped release/read-only test credentials when the
  validation gates are ready; do not print tokens or alter scopes silently.

See [issue #4](https://github.com/Chiv2-Community/argonsdk-builder-image/issues/4).

The separate Wine experiment uses recipient-encrypted Actions artifacts solely
to transfer a Windows cooker to a locally held private key. No plaintext engine,
SDK, or private key is uploaded; this is not registry publication or a supported
image release. See `linux-feasibility.md` for the transfer and validation limits.
