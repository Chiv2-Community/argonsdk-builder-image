#!/bin/bash
set -euo pipefail
case "${1:?specify setup or compile}" in
    setup)
        # Root Setup.sh adds --prompt; combining it with --force skips dependencies.
        bash Engine/Build/BatchFiles/Linux/GitDependencies.sh --force --threads=8 --max-retries=2 \
            --cache=/home/ue/.cache/ue-gitdeps </dev/null
        test -s .ue4dependencies
        bash Engine/Build/BatchFiles/Linux/Setup.sh
        ;;
    compile)
        test -s .ue4dependencies
        ./GenerateProjectFiles.sh
        make UE4Editor ShaderCompileWorker UnrealPak UnrealLightmass CrashReportClient \
            ARGS='-NoDebugInfo -MaxParallelActions=8'
        test -x Engine/Binaries/Linux/UE4Editor
        test -x Engine/Binaries/Linux/ShaderCompileWorker
        test -x Engine/Binaries/Linux/UnrealPak
        ;;
    *) exit 2 ;;
esac
