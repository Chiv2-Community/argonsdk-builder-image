# syntax=docker/dockerfile:1
# Supply an authorized Linux UE image pinned by digest. No public default.
ARG UE_BASE_IMAGE
FROM ${UE_BASE_IMAGE} AS sdk-source
USER ue
WORKDIR /home/ue
COPY --chown=ue:ue build-lock.json /opt/argonsdk-builder/build-lock.json
COPY --chown=ue:ue scripts/builder.py /opt/argonsdk-builder/scripts/builder.py
RUN python3 /opt/argonsdk-builder/scripts/builder.py prepare --workspace /home/ue/argon-work
ENV ARGON_SDK_ROOT=/home/ue/argon-work/ArgonSDK

# Experimental: SDK plugins may require Linux portability fixes.
# This builds a Linux editor, NOT a Windows cooker or a Windows PAK.
FROM sdk-source AS linux-builder
RUN "${UE_ROOT}/Engine/Build/BatchFiles/Linux/Build.sh" \
    TBLEditor Linux Development "${ARGON_SDK_ROOT}/TBL.uproject" -WaitMutex -NoHotReload
WORKDIR /home/ue
ENTRYPOINT []
CMD ["/bin/bash"]
