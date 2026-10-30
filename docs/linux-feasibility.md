# Linux Windows-cooking investigation

Investigation started 2026-10-24. The pinned native Linux engine image built
successfully on 2026-10-25. The reusable SDK image also built with the verified
RHI build-rule patch below. No Windows-target cook has succeeded yet.

## Source-mod probe: 2026-10-27

- Rebuilt pristine pinned UE and the SDK in local Linux image
  `sha256:31af0d74190f6f67e28295640175eef9152dc0bb372ad719bb6e263b773a6391`.
  The pristine engine is at `/opt/argon-stock-engine`; the available patched
  image was used only as a toolchain base. This oversized probe is not a
  publication candidate.
- Prepared the external reference's 41 source packages in independent SDK
  copies, with recorded source hashes and the single-package config override.
- Actual native `WindowsNoEditor` cooking exited 1 at platform discovery:
  `Invalid target platform specified (WindowsNoEditor)`. Only Android and Linux
  target variants were available. No Windows-target PAK was created.
- The separate Linux-target diagnostic initially failed loading a copied SDK
  plugin. The library existed, but generated ELF RPATHs depended on the
  template's original path depth. The local probe now resolves library paths
  from the isolated SDK and pristine engine explicitly. With that correction,
  the Linux-target cook returned zero: 41 packages, 82 cooked files, 17.94 seconds.
  Native UnrealPak create/test/list/extract and extracted-file hash checks passed
  in another 1.96 seconds. The PAK is 1,535,091 bytes, SHA-256
  `449ed751ceb88c1957369318367428f82c13a8db821eb523e3fcd3e5a691bbdb`.
- That Linux-target result is not Windows compatibility evidence. The SDK clears
  Linux `TargetedRHIs`; the pinned Linux target platform supports Vulkan/OpenGL
  shader formats, not `PCD3D_SM5`. A successful asset inventory and PAK integrity
  check do not establish working Windows material shaders. No game-runtime
  validation has been performed. The production Linux backend remains blocked.
- Available patched engine `ff1252c75809` cannot substitute for pristine UE:
  its `Engine.AssemblyInstance` conflicts with ArgonSDK's `TBL.AssemblyInstance`.
  Do not remove SDK classes to bypass this incompatible base.

Evidence is retained locally under
`~/.cache/argonsdk-builder/linux-native-mod-probe/`. No licensed image or PAK
has been uploaded.

## Windows cooker under Wine: experiment started 2026-10-30

`windows-wine-probe.yml` builds the pinned Windows engine and a workload-free
Windows SDK template. It omits Git metadata, build intermediates, DDC, and saved
job state from the transfer archive, then encrypts it with pinned age 1.3.2.
Only ciphertext and checksums are uploaded, with one-day retention. The public
`WINE_PROBE_RECIPIENT` repository variable selects a locally held X25519 identity;
the private key never enters Actions or the repository. No GHCR image is pushed.

The consumer must select the trusted workflow run/commit, decrypt locally,
verify the archive and per-file manifest, and test Windows executables in an
isolated Wine prefix. Recipient encryption is not a signature or proof of sender.
This transfer experiment does not relax the licensed-image publication gates.
Wine source cooking and Windows-game compatibility remain unvalidated.

## Verified observations

- The required engine is UE `4.25-plus` commit
  `2d1aaeede6780b14c3ef97272e8a68c3429d8231`.
- Its `ShaderFormatD3D` module uses Windows platform wrappers and directly
  includes `D3D11.h` and `D3Dcompiler.h`. The build rules depend on `DX11` and
  stage Windows DirectX compiler DLLs for Win64. A native Linux editor build
  alone is therefore not evidence of working Windows shader cooking.
- `TargetPlatform.Build.cs` adds `ShaderFormatD3D` only for Win32/Win64 hosts.
  Enabling Windows platform discovery alone would not supply that shader
  compiler on Linux; any native backend must address both paths explicitly.
- The built engine passed its version/tool-hash receipt check in a nonroot,
  read-only, network-disabled container. `ldd` found no missing runtime libraries
  for UE4Editor, ShaderCompileWorker, or UnrealPak.
- Native UnrealPak passed a compressed binary-payload create/test/list/extract
  roundtrip in that isolated runtime. Read-only engine use requires per-job
  writable mounts at `Engine/DerivedDataCache` and
  `Engine/Programs/UnrealPak/Saved`; the program's DDC graph did not honor the
  attempted `UE-LocalDataCachePath` override. This validates packaging tools,
  not cooked-asset compatibility. Extraction syntax is `-Extract <directory>`,
  not `-Extract=<directory>`.
- A bounded empty-project commandlet reached target-platform discovery but
  rejected `-TargetPlatform=WindowsNoEditor` with exit 1: `Invalid target platform
  specified (WindowsNoEditor)`. The available platforms were Android and Linux
  variants only. This is an observed stock-engine blocker, not a claim that a
  patched native backend is impossible. The probe cooked no mod assets.
- The first SDK build compiled the TBL sources but failed linking
  `libUE4Editor-TBL.so`: undefined `GMaxRHIFeatureLevel`. Its pinned build rules
  omit the direct RHI dependency used by an inline Engine helper. A separate
  experimental image built successfully after adding only that dependency;
  no classes were removed and the pinned source checkout remains unchanged.
  The reusable Linux recipe now applies that transformation explicitly and
  validates its receipt against the committed source. Provenance identifies
  the patch and retains `dirty=true`; unrelated changes are rejected.
- The built SDK image passed its actual consumer preparation path as nonroot
  with a read-only root and disabled network: independent SDK copy, preserved
  prebuilt TBL module, matching external input hashes, explicit patch identity,
  unchanged template, and no copied Git metadata. This is input/workspace
  validation, not a source-to-PAK result.
- The current SDK image Dockerfile builds only a Linux editor. Its cook/package
  commands still require Windows. There is no implemented Wine backend.
- Storage was reclaimed by the user: about 349 GiB was available when the first
  local image build started. The development host still has a Linux-only Docker
  daemon; this does not provide a native Windows container runner.
- First build attempt exposed the root setup wrapper's `--prompt`/`--force`
  conflict. GitDependencies returned success without downloading dependencies;
  project generation then failed. The build now invokes dependency setup
  directly and requires its nonempty completion manifest before compilation.
- Subsequent attempts reached dependency downloads but failed Mono TLS trust.
  The development base has system CA roots but no populated Mono trust stores
  or packaged `cert-sync`. A separate HTTPS probe succeeded after importing
  those roots into Mono's legacy and BTLS stores. The engine build now performs
  that import and selects system Mono; certificate verification stays enabled.

These are source/environment observations, not a proof that Linux Windows
cooking is impossible.

## Next experiments

1. Establish the Windows container baseline on a compatible Windows Docker host.
   Native Windows source-to-PAK already passes; this is not container acceptance.
2. For native Linux cooking, enumerate available target/shader format modules
   and run a small source-to-WindowsNoEditor cook. Preserve errors and identify
   necessary platform/compiler patches; a Linux-target cook is not success.
3. In a separate Linux image, test the pinned Windows editor, shader workers,
   and UnrealPak under Wine. Start with a generic content fixture before the
   external reference workload. Do not reuse a host Wine prefix or cooked files.
4. Select a backend only after a complete Windows-target cook, package integrity
   test, structural comparison, and Windows-game runtime validation. Document
   missing tools/licensing prerequisites rather than silently skipping them.

Keep image publication gated on the project's validation and access checks.

## Sources

- [Candidate Direct3D shader compiler](https://github.com/EpicGames/UnrealEngine/blob/2d1aaeede6780b14c3ef97272e8a68c3429d8231/Engine/Source/Developer/Windows/ShaderFormatD3D/Private/D3DShaderCompiler.cpp#L17-L40)
- [Candidate Direct3D module build rules](https://github.com/EpicGames/UnrealEngine/blob/2d1aaeede6780b14c3ef97272e8a68c3429d8231/Engine/Source/Developer/Windows/ShaderFormatD3D/ShaderFormatD3D.Build.cs#L23-L31)
- [Linux implementation issue](https://github.com/Chiv2-Community/argonsdk-builder-image/issues/5)

Epic source links require an appropriately authorized GitHub account.
