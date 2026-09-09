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

# ------------------------------------------------------------------------ final
FROM runtime-base AS converter
ARG PLATFORM_VERSION=unknown
ARG EDT_VERSION=unknown
ARG REVISION=r1

LABEL org.opencontainers.image.title="1c-converter" \
      org.opencontainers.image.description="1C configuration converter: ibcmd + 1cedtcli + thin orchestration (based on approaches from arkuznetsov/1CFilesConverter and ShadobaAI/kafka-tools)" \
      org.opencontainers.image.version="${PLATFORM_VERSION}+edt${EDT_VERSION}" \
      onec.converter.platform-version="${PLATFORM_VERSION}" \
      onec.converter.edt-version="${EDT_VERSION}" \
      onec.converter.revision="${REVISION}"

COPY --from=platform-installer /opt/1cv8 /opt/1cv8
COPY --from=edt-installer /opt/1C/1CE /opt/1C/1CE

RUN find /opt/1cv8 \( \
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
