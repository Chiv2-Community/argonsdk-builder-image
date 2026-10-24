# argonsdk-builder-image

Reusable ArgonSDK editor environment and Windows content-mod build scaffold for
the proposed `Chiv2-Community/argonsdk-builder-image` repository.

**Status:** orchestration and unit tests only. SDK compilation, engine cooking,
and runtime compatibility remain untested. Nothing has been published.

## Inputs

- `build-lock.json` pins ArgonSDK and records a candidate UE revision.
- A caller-provided mod descriptor selects source, content location, package
  namespace, and artifact name. No particular mod is bundled in the image.

Create `mod.json` outside this repository, replacing the example URL and commit
with your repository and its exact 40-character commit SHA:

```json
{
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

This scaffold handles content-only mods, including maps. It does not implement
native plugin distribution, automatic dependency installation, or arbitrary
base-game asset replacement. Supply required dependency assets in a compatible
SDK environment before cooking; dependencies outside the selected mod directory
are deliberately excluded from its PAK.

## Windows build

Provision a trusted, disposable Windows x64 runner with:

- An authorized UE 4.25 editor/toolchain, matching compiler and Windows SDK.
  `4.25-plus` is an untested candidate; validate compatibility for each mod.
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

Existing checkouts, cooked directories, and artifacts are never replaced. Use
fresh workspace/output paths for each run. The cook explicitly includes the
selected mod directory and disables Blueprint nativization. Packaging requires
matching source/cooked package inventories and includes only that directory's
Unreal packages and sidecars.

Outputs include `<name>.pak`, `<name>.pak.sha256`, response-file inputs, PAK test
and inventory logs, and `manifest.json` with declared source inputs, engine
`Build.version`, and cooked-file hashes. The engine candidate in the lock is
not an enforced or verified installed-engine identity.

For GitHub Actions, set repository variable `UE_ROOT`, label the Windows runner
`argonsdk-builder`, and manually dispatch `windows-baseline.yml` with the mod
descriptor JSON in the `mod_config` input. It uploads job artifacts only.
Do not execute untrusted mod repositories or pull requests on this runner.

## Experimental Linux image

`Dockerfile` layers ArgonSDK onto an existing, authorized native Linux UE image.
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

Tests use fake subprocesses, not Unreal. `check.yml` runs these engine-free
checks on hosted Linux. No engine/SDK/game binaries are stored here, and no
workflow publishes images or creates releases or remote repositories.
