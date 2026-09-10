# syntax=docker/dockerfile:1
#
# 1c-converter: single Linux image with ibcmd + 1cedtcli + thin orchestrator.
#
# Docker build is based on proven approaches from ShadobaAI/kafka-tools
# (.github/ci-images/docker/Dockerfile, Apache License 2.0) — see THIRD_PARTY_NOTICES.md.
# Multi-stage scheme keeps the closed 1C distributions inside installer stages only;
# runtime stages receive the installed directories without source archives.
#
# Distributions are supplied via the BuildKit named context `vendor`
# (compose: build.additional_contexts.vendor=./vendor):
#   vendor/platform/ — 1C:Enterprise 8.3 server (deb64_*.zip or server64_*.zip), ibcmd
#   vendor/edt/      — 1C:EDT offline (1c_edt_distr_offline_*_linux_x86_64.tar.gz)
#
# ctool1cd (configuration storage reader, GPL-3) is built from the public
# upstream source pinned by TOOL1CD_REF — no closed distribution required.

ARG BASE_IMAGE=debian:bookworm-slim

# ---------------------------------------------------------------- runtime base
# Combined runtime dependencies:
#   platform (kafka-tools platform-runtime-base): libgssapi-krb5-2, libicu72,
#     libgsf-1-114, locales, procps, unixodbc + ru_RU.UTF-8
#   EDT (kafka-tools edt-runtime-base): fontconfig, libasound2, libgtk-3-0,
#     libxtst6, openjdk-17-jre-headless
#   converter: python3 (thin orchestration layer)
FROM ${BASE_IMAGE} AS runtime-base

ENV DEBIAN_FRONTEND=noninteractive
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
      ca-certificates \
      fontconfig \
      libasound2 \
      libgssapi-krb5-2 \
      libgsf-1-114 \
      libgtk-3-0 \
      libicu72 \
      libxtst6 \
      locales \
      openjdk-17-jre-headless \
      procps \
      psmisc \
      python3 \
      unixodbc \
      unzip \
  && localedef -i ru_RU -c -f UTF-8 -A /usr/share/locale/locale.alias ru_RU.UTF-8 \
  && rm -rf /var/lib/apt/lists/*

ENV LANG=ru_RU.UTF-8 \
    LANGUAGE=ru_RU:ru \
    LC_ALL=ru_RU.UTF-8

# ------------------------------------------------------------ platform installer
FROM runtime-base AS platform-installer
ARG PLATFORM_COMPONENTS=server,ru

COPY docker/scripts/install-platform.sh /usr/local/sbin/onec-image/install-platform.sh

RUN --mount=type=bind,from=distr,source=.,target=/distr,readonly \
    bash /usr/local/sbin/onec-image/install-platform.sh /distr/platform "${PLATFORM_COMPONENTS}" \
  && test -x /opt/1cv8/current/ibcmd \
  && rm -rf /tmp/* /var/tmp/*

# ------------------------------------------------------------------ EDT installer
FROM runtime-base AS edt-installer
ARG EDT_PLATFORM_SUPPORT=8.3.27

COPY docker/scripts/install-edt.sh /usr/local/sbin/onec-image/install-edt.sh

RUN --mount=type=bind,from=distr,source=.,target=/distr,readonly \
    bash /usr/local/sbin/onec-image/install-edt.sh /distr/edt "${EDT_PLATFORM_SUPPORT}" \
  && find /opt/1C/1CE \( \
        -type d -name jmods -o \
        -type d -name include -o \
        -type d -name man -o \
        -type d -name demo -o \
        -type d -name legal \
      \) -prune -exec rm -rf {} + \
  && rm -rf /tmp/* /var/tmp/*

# --------------------------------------------------------------- tool1cd builder
# ctool1cd reads the 1C configuration storage (1cv8ddb.1CD) directly,
# without the 1C platform: dumps a .cf of any storage version (-drc) and
# exports storage tables (VERSIONS/USERS -> version author/date/comment).
# Source: https://github.com/e8tools/tool1cd (GPL-3, see THIRD_PARTY_NOTICES.md).
FROM runtime-base AS tool1cd-builder
ARG TOOL1CD_REF=f0361ad849076507684fe77bac7d59569a7ba244

COPY docker/patches/tool1cd-depot-ver100.patch /tmp/patches/tool1cd-depot-ver100.patch

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
      ca-certificates \
      cmake \
      curl \
      g++ \
      libboost-filesystem-dev \
      libboost-regex-dev \
      libboost-system-dev \
      make \
      patch \
      zlib1g-dev \
  && rm -rf /var/lib/apt/lists/* \
  && curl -fsSL "https://github.com/e8tools/tool1cd/archive/${TOOL1CD_REF}.tar.gz" \
     | tar -xz -C /tmp \
  && cd /tmp/tool1cd-* \
  && patch -p1 < /tmp/patches/tool1cd-depot-ver100.patch \
  && sed -i '/gtool1cd/d' CMakeLists.txt \
  && mkdir build && cd build \
  && cmake .. -DCMAKE_BUILD_TYPE=Release > /dev/null \
  && make -j"$(nproc)" > /dev/null 2>&1 \
  && mkdir -p /out/bin /out/lib \
  && cp bin/ctool1cd /out/bin/ \
  && cp lib/libtool1cd.so /out/lib/ \
  && rm -rf /tmp/tool1cd-* /var/lib/apt/lists/*

# ------------------------------------------------------------------------ final
FROM runtime-base AS converter
ARG PLATFORM_VERSION=unknown
ARG EDT_VERSION=unknown
ARG TOOL1CD_REF=f0361ad849076507684fe77bac7d59569a7ba244
ARG REVISION=r1

LABEL org.opencontainers.image.title="1c-converter" \
      org.opencontainers.image.description="1C configuration converter: ibcmd + 1cedtcli + ctool1cd (storage) + thin orchestration (based on approaches from arkuznetsov/1CFilesConverter and ShadobaAI/kafka-tools)" \
      org.opencontainers.image.version="${PLATFORM_VERSION}+edt${EDT_VERSION}" \
      onec.converter.platform-version="${PLATFORM_VERSION}" \
      onec.converter.edt-version="${EDT_VERSION}" \
      onec.converter.tool1cd-ref="${TOOL1CD_REF}" \
      onec.converter.revision="${REVISION}"

COPY --from=platform-installer /opt/1cv8 /opt/1cv8
COPY --from=edt-installer /opt/1C/1CE /opt/1C/1CE
COPY --from=tool1cd-builder /out/bin/ctool1cd /usr/local/bin/ctool1cd
COPY --from=tool1cd-builder /out/lib/libtool1cd.so /usr/local/lib/libtool1cd.so

# git: storage-sync commits; boost/zlib: ctool1cd runtime (icu comes via platform deps)
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
      git \
      libboost-filesystem1.74.0 \
      libboost-regex1.74.0 \
      zlib1g \
  && rm -rf /var/lib/apt/lists/* \
  && ldconfig \
  && find /opt/1cv8 \( \
        -type d -iname doc -o \
        -type d -iname docs -o \
        -type d -iname help -o \
        -type d -iname examples \
      \) -prune -exec rm -rf {} + \
  && rm -rf /usr/share/doc/* /usr/share/man/* /usr/share/info/* /usr/share/lintian /usr/share/linda /tmp/* /var/tmp/*

ENV PATH="/opt/1cv8/current:/opt/1C/1CE/components/1cedtcli:${JAVA_HOME}/bin:${PATH}"

COPY converter/ /opt/converter/

RUN printf '#!/bin/sh\nexec /opt/1cv8/current/ibcmd "$@"\n' > /usr/local/bin/ibcmd \
  && printf '#!/bin/sh\nexec /opt/1C/1CE/components/1cedtcli/1cedtcli "$@"\n' > /usr/local/bin/1cedtcli \
  && printf '#!/bin/sh\nexec env PYTHONPATH=/opt/converter python3 -m onec_convert "$@"\n' > /usr/local/bin/1c-convert \
  && chmod +x /usr/local/bin/ibcmd /usr/local/bin/1cedtcli /usr/local/bin/1c-convert \
  && mkdir -p /work/input /work/output /work/cache /var/1C/licenses \
  && 1c-convert selfcheck

WORKDIR /work

CMD ["bash"]
