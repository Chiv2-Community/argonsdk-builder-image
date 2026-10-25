# Linux Windows-cooking investigation

Investigation started 2026-10-24. The pinned native Linux engine image built
successfully on 2026-10-25. No SDK build or Windows-target cook has succeeded yet.

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
- A bounded empty-project commandlet reached target-platform discovery but
  rejected `-TargetPlatform=WindowsNoEditor` with exit 1: `Invalid target platform
  specified (WindowsNoEditor)`. The available platforms were Android and Linux
  variants only. This is an observed stock-engine blocker, not a claim that a
  patched native backend is impossible. The probe cooked no mod assets.
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

1. Complete the SDK build on the pinned Linux engine with bounded parallelism.
   Establish the Windows container baseline on a compatible Windows Docker host.
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
