# argonsdk-builder-image

Reusable ArgonSDK editor environment and Windows content-mod build scaffold for
the proposed `Chiv2-Community/argonsdk-builder-image` repository.

**Status:** orchestration and unit tests only. SDK compilation, engine cooking,
and runtime compatibility remain untested. Nothing has been published.

## Inputs

- `build-lock.json` pins ArgonSDK and the required UE **4.25-plus** source revision.
- A caller-provided mod descriptor selects source, content location, package
  namespace, and artifact name. No particular mod is bundled in the image.

Create `mod.json` outside this repository, replacing the example URL and commit
with your repository and its exact 40-character commit SHA:

```json
{
  "schema_version": 1,
  "name": "ExampleMod",
  "repository": "https://github.com/your-org/your-mod.git",
  "commit": "0123456789abcdef0123456789abcdef01234567",
  "content_path": "Content",
  "package_path": "Mods/AgMods/ExampleMod"
}
```

- `content_path`: directory relative to the mod checkout; defaults to `Content`.
- `package_path`: destination relative to the SDK's `Content` directory. Use the
  mod's existing package namespace, not a new name; both `Mods/ExampleMod` and
  `Mods/AgMods/ExampleMod` are supported.
- `name`: output filename stem, producing `ExampleMod.pak` and its checksum.
- Source must be a trusted HTTPS repository pinned to a commit. Relative paths
  cannot contain parent traversal, backslashes, or absolute paths.

The v1 format is described in `schemas/mod.schema.json`; the CLI also checks
portable names, credential-free repository URLs, and namespace overlap.
Unversioned scaffold descriptors are interpreted as v1. Unknown fields fail.
Run `python scripts/builder.py --mod-config ../mod.json validate-mod` before a
build. Content-directory and workspace paths may contain spaces; Unreal package
namespaces use only letters, digits, underscores, and forward slashes.

Optional `dependencies` is an array of descriptors with the same source fields
but no nested dependencies. Each is copied into its declared package namespace
for cooking. Duplicate, ancestor/descendant, and case-insensitive overlapping
namespaces are rejected. Dependency files are never included in the primary
mod PAK. Provide every required external content dependency explicitly.

This scaffold handles content-only mods, including maps. It does not implement
native plugin distribution, automatic registry dependency resolution, or
arbitrary base-game asset replacement. Native/game dependencies must already be
available in a compatible SDK; declared content dependencies are staged during
preparation and excluded from the selected mod PAK.

## Windows build

Provision a trusted, disposable Windows x64 runner with:

- An authorized UE **4.25-plus** editor/toolchain built from the locked commit,
  with its matching compiler and Windows SDK. Stock 4.25/4.25.4 is rejected.
- Git, Python 3.11+, and PowerShell 7 on PATH.
- Network access to the selected repositories and recorded submodules.
- Any game assets missing from ArgonSDK that the mod requires.
- Enough disk/RAM for engine, SDK, shader cooking, and dependency compilation.
  Start with 32 GiB RAM and 300 GiB free disk; measure actual usage.

From PowerShell at this repository root:

```powershell
python scripts/builder.py --mod-config ../mod.json prepare --workspace work
python scripts/builder.py build-editor --engine $env:UE_ROOT --sdk work/ArgonSDK
python scripts/builder.py --mod-config ../mod.json cook --engine $env:UE_ROOT --sdk work/ArgonSDK
python scripts/builder.py --mod-config ../mod.json package --engine $env:UE_ROOT --sdk work/ArgonSDK --output dist
```

`UE_ROOT` must contain `Engine/`. Preparation checks out recorded submodule
commits, never remote branch heads, and copies the selected content directory
into the SDK. Without `--mod-config`, `prepare` checks out only ArgonSDK.

### Use an image's SDK template

`prepare --sdk-template <path>` copies an existing SDK instead of downloading
it. This defaults to `ARGON_SDK_ROOT` when set by the image. The template must
retain Git metadata, match the locked commit, and have clean, initialized
submodules at recorded commits. Keep that template read-only for consumers.

For an already mounted source checkout, add `--mod-source <path>`. This avoids
downloading the primary mod; dependencies still use their pinned repositories.
A Git mount must match its declared clean commit. Plain content mounts are
allowed but are identified by content hashes only, not claimed to match a Git
commit. All source mounts are read-only inputs to the builder.

```powershell
python scripts/builder.py --mod-config ../mod.json prepare --workspace work --sdk-template $env:ARGON_SDK_ROOT --mod-source ../mod-source
```

Each workspace is reserved atomically. Jobs use independent copies, never
hardlinks to the SDK or source mount. Git metadata and top-level SDK cook/cache
directories are omitted from template copies. Input symlinks/reparse points,
case collisions, and workspace/input overlap are rejected. A failed preparation
is retained for diagnosis and cannot be reused; select a new workspace path.

Existing checkouts, cooked directories, and artifacts are never replaced. Use
fresh workspace/output paths for each run. The cook explicitly includes the
selected mod directory and disables Blueprint nativization. Packaging requires
matching source/cooked package inventories and includes only that directory's
Unreal packages and sidecars.

Before cook/package, prepared mod and dependency content hashes are rechecked;
packaging also rejects a descriptor/lock different from preparation. This does
not attest arbitrary code execution inside Unreal or protect a concurrently
mutated mount: run trusted mods in isolated jobs with read-only input mounts.

Outputs include `<name>.pak`, `<name>.pak.sha256`, response-file inputs, PAK test
and inventory logs, and `manifest.json`. It includes prepared source receipts,
actual SDK/submodule identities, content/tool hashes, and verified engine
metadata. Build, cook, package, and SDK-image construction reject a different
engine branch/revision. Engines must retain clean Git metadata at the locked
commit or have a build receipt with matching version/tool hashes. Missing
identity is an error, not a version-label-only fallback. Receipts are integrity
records from a trusted build, not independent signatures or proof of gameplay
compatibility.
Cook receipts require a complete source/cooked package inventory and record
the command line, engine identity, and cooked file hashes. Packaging rejects
files or an engine that no longer match that receipt.
Packaging pre-cooked content without that receipt is explicitly marked
`no_cook_receipt`, not presented as evidence of a source-to-PAK rebuild.

Pass `prepare --image-reference registry/image@sha256:...` (or set
`BUILDER_IMAGE_REFERENCE`) to record the consumer's image digest. This field is
caller-supplied and explicitly not runtime-attested; absence is recorded as
null. Registry digest verification remains the caller's responsibility.

For GitHub Actions, set repository variable `UE_ROOT`, label the Windows runner
`argonsdk-builder`, and manually dispatch `windows-baseline.yml` with the mod
descriptor JSON in the `mod_config` input. It uploads job artifacts only.
Do not execute untrusted mod repositories or pull requests on this runner.

## Experimental Windows image

`Dockerfile.windows` layers the pinned SDK and built `TBLEditor` modules onto an
authorized Windows Server Core engine build base. It contains no caller mod and
runs as `ContainerUser`. The base must provide Python 3.11+, Git, Visual Studio
C++ build tools, a matching Windows SDK, and `UE_ROOT` with the pinned built
Win64 engine. Engine metadata and build paths must be accessible to
`ContainerUser`; Git metadata must be owned by that account or explicitly
trusted by the base. No globally trusted Git-directory wildcard is required.

On a compatible Windows Docker host:

```powershell
docker build -f Dockerfile.windows --build-arg UE_BASE_IMAGE='<authorized-base>@sha256:<digest>' -t argonsdk-windows:local .
docker run --rm argonsdk-windows:local validate-lock
```

The entrypoint is `builder.py`. Use the same descriptor and `prepare`, `cook`,
and `package` commands above, with container paths and writable per-job work
mounts. Preparation defaults to copying the image's `ARGON_SDK_ROOT` template.
Mount input sources read-only. Do not mount host engine directories or reuse
workspaces between jobs.

This Dockerfile has not been built or runtime-validated. GitHub's hosted
`windows-2022` runner is the selected build host; `windows-host.yml` tests its
Docker/container runtime, compiler inventory, and available storage without
accessing licensed sources. Engine source access uses the `UE_GITHUB_TOKEN`
Actions secret. A passing host preflight or native Windows workflow is not
container build/cook validation. Publication remains blocked.

## Experimental Linux image

`Dockerfile` layers ArgonSDK onto an existing, authorized native Linux UE
4.25-plus image and checks its pinned identity before downloading SDK content.
It contains no caller mod. The base must provide user `ue` with writable home,
`UE_ROOT`, a built Linux engine, Git, Python 3.11+, and build dependencies.

```sh
docker build --build-arg UE_BASE_IMAGE='<private-registry>/<image>@sha256:<digest>' \
  --target sdk-source -t argonsdk-source:local .
docker build --build-arg UE_BASE_IMAGE='<private-registry>/<image>@sha256:<digest>' \
  --target linux-builder -t argonsdk-builder:local .
```

- `sdk-source` prepares the pinned SDK without compiling its modules.
- `linux-builder`, the default target, attempts to build `TBLEditor` for Linux.
  Plugin/platform failures remain investigation points. Do not hide failures by
  stripping classes that mods need.
- No Wine environment or native Windows cross-cooker is implemented. Windows
  cook/package commands deliberately reject native Linux execution.

The optional manual `linux-image.yml` workflow requires a trusted Linux x64
runner labeled `argonsdk-builder`, Docker access, authorized registry read
access, and repository variable `UE_BASE_IMAGE` pinned by digest. It retains
the image in the runner's local Docker store; it never pushes it.

Do not publish engine/SDK images to a public registry. Review Epic's license,
SDK/game asset rights, and actual registry download access before distribution.
A private source repository alone does not make an image private.
The selected publication target is private GitHub Container Registry (GHCR),
not Forgejo. Publishing remains blocked on backend/runtime validation, approved
licensed recipients, and verified private package/download permissions.
See [publication gates](docs/publication.md) for candidate, access-test, and
release-promotion requirements.

### Build the Linux engine locally

`Dockerfile.engine` and `scripts/build_engine_image.py` build the locked engine
from an authorized local UE Git checkout. They archive only the pinned commit,
not its working tree, Git credentials, or previously downloaded binaries.
Provide a Linux x64 build base with user `ue` (UID/GID 1001), Python 3.11+, Git,
Mono with `mcs` and `Mono.Security`, a populated system CA bundle, native build
tools, and UE's Linux runtime dependencies. The sibling
`ubuntu-ue` tools image is the initial development base; a published base must
be authorized and pinned by digest.

```sh
python3 scripts/build_engine_image.py --source /path/to/UnrealEngine \
  --context /large-build-disk/new-engine-context \
  --base-image '<authorized-build-base>@sha256:<digest>' \
  --tag argonsdk-ue4.25-plus:local
```

The context must be new. Setup downloads dependencies/toolchain, then compiles
the Linux editor, shader worker, and packaging tools with bounded parallelism.
The isolated tree's legacy CDN URLs are upgraded to HTTPS with before/after
hashes recorded. Dependency setup and compilation are separate cached layers;
a nonempty dependency completion manifest is required before compilation.
The build imports the base's system CA roots into Mono's legacy and BTLS stores
and uses system Mono; TLS certificate verification stays enabled.
The resulting `.builder-engine.json` records the source archive and tool hashes.
No source checkout is modified, and no image is pushed.

Use that engine image as `UE_BASE_IMAGE` for the SDK image. This produces Linux
editor tools only; Windows-target cooking on Linux remains a separate,
unimplemented backend. See `docs/linux-feasibility.md` for investigation notes.

## Validation gates

1. Build the SDK editor and cleanly cook a representative content-only mod.
2. Check package names, imports, defaults, Blueprint bytecode, materials, and
   other cooked assets against expected behavior.
3. Test the mod in-game, including multiplayer and dedicated server where used.
4. Repeat clean builds to measure determinism before claiming reproducibility.
5. Use the Windows result as the reference for Linux/Wine cooking experiments.

Matching engine version labels or a successful `UnrealPak -Test` does not prove
functional equivalence. Native plugin packaging requires separate work.

## Scaffold checks

```sh
python3 -m unittest discover -s tests -v
python3 scripts/builder.py validate-lock
go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.7 -shellcheck='' .github/workflows/*.yml
```

Tests use real local Git/filesystem fixtures and fake Unreal subprocesses.
`check.yml` runs engine-free checks on hosted Linux and Windows; workflow lint
runs on Linux. No engine/SDK/game binaries are stored here, and no
workflow publishes images or creates releases or remote repositories.
