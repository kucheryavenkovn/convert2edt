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
      libglu1-mesa \
      libgtk-3-0 \
      libicu72 \
      libsm6 \
      libxtst6 \
      libwebkit2gtk-4.0-37 \
      libxxf86vm1 \
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
ARG TOOL1CD_REF=625ac1a47b6ed63bba2848842daf1909813f84d4

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
      zlib1g-dev \
  && rm -rf /var/lib/apt/lists/* \
  && curl -fsSL "https://github.com/e8tools/tool1cd/archive/${TOOL1CD_REF}.tar.gz" \
     | tar -xz -C /tmp \
  && cd /tmp/tool1cd-* \
  && sed -i '/gtool1cd/d' CMakeLists.txt \
  && mkdir build && cd build \
  && cmake .. -DCMAKE_BUILD_TYPE=Release > /dev/null \
  && make -j"$(nproc)" > /dev/null 2>&1 \
  && mkdir -p /out/bin /out/lib \
  && cp bin/ctool1cd /out/bin/ \
  && cp lib/libtool1cd.so /out/lib/ \
  && rm -rf /tmp/tool1cd-* /var/lib/apt/lists/*


# ------------------------------------------------------- crs (repository server)
# Thin target: platform server + configuration repository server (crs deb).
# The converter image does NOT include crs — it only connects over tcp://.
FROM runtime-base AS crs
COPY docker/scripts/install-platform.sh /usr/local/sbin/onec-image/install-platform.sh

RUN --mount=type=bind,from=distr,source=.,target=/distr,readonly \
    CRS_INSTALL=1 bash /usr/local/sbin/onec-image/install-platform.sh /distr/platform "server,ru" \
  && test -x /opt/1cv8/current/ibcmd \
  && rm -rf /tmp/* /var/tmp/* /usr/share/doc/* /usr/share/man/*

# repository databases live here (compose mounts a volume)
VOLUME /repos


# ------------------------------------------------------------------------ final
FROM runtime-base AS converter
ARG PLATFORM_VERSION=unknown
ARG EDT_VERSION=unknown
ARG TOOL1CD_REF=f0361ad849076507684fe77bac7d59569a7ba244
ARG REVISION=r1
# gitsync engine (alternative storage reader): OneScript + gitsync with
# tool1CD (native storage access, no 1cv8 client needed) and edtExport
# (XML -> EDT via 1cedtcli) plugins. Public sources only.
ARG GITSYNC_SUPPORT=1
ARG OSCRIPT_VERSION=1.9.4
# программная лицензия 1С привязывается к MAC + /etc/machine-id; без фиксации
# каждая пересборка образа генерирует новый machine-id и инвалидрует лицензию.
# Значение по умолчанию = machine-id образа, на котором лицензия активирована.
ARG MACHINE_ID=72a3ee44d3a44a51925e4faeeb85cc9e

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

# git: storage-sync commits; boost/zlib: ctool1cd runtime (icu comes via platform deps);
# xvfb+xauth: 1cv8 client (DESIGNER batch) requires an X display even headless;
# openbox/dbus/xdotool/x11vnc/mscorefonts: GUI stack for the 1C client
# (interactive software license obtain over VNC, see docker/scripts/license-gui.sh;
# approach from ShadobaAI/kafka-tools `client` image, Apache-2.0)
RUN sed -i 's/^Components: main$/Components: main contrib/' /etc/apt/sources.list.d/debian.sources \
  && echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | debconf-set-selections \
  && apt-get update \
  && apt-get install -y --no-install-recommends \
      dbus-x11 \
      git \
      iproute2 \
      libboost-filesystem1.74.0 \
      libboost-regex1.74.0 \
      libcups2 \
      libegl1 \
      libgl1 \
      libsecret-1-0 \
      libxinerama1 \
      libxrandr2 \
      libxrender1 \
      openbox \
      ttf-mscorefonts-installer \
      x11vnc \
      xauth \
      xdotool \
      xvfb \
      zlib1g \
  && rm -rf /var/lib/apt/lists/* \
  && ldconfig \
  && find /opt/1cv8 \( \
        -type d -iname doc -o \
        -type d -iname docs -o \
        -type d -iname help -o \
        -type d -iname examples \
      \) -prune -exec rm -rf {} + \
  # платформа бандлит старый libstdc++, который несовместим с bookworm-webkit
  # (1cv8 client грузит libwebkit2gtk) — убираем, системный новее и совместим
  && find /opt/1cv8 -maxdepth 3 -name 'libstdc++.so.6*' -delete \
  && printf '%s\n' "${MACHINE_ID}" > /etc/machine-id \
  && mkdir -p /var/lib/dbus && cp /etc/machine-id /var/lib/dbus/machine-id \
  && rm -rf /usr/share/doc/* /usr/share/man/* /usr/share/info/* /usr/share/lintian /usr/share/linda /tmp/* /var/tmp/*

COPY docker/scripts/install-gitsync.sh /usr/local/sbin/onec-image/install-gitsync.sh
RUN bash /usr/local/sbin/onec-image/install-gitsync.sh "${GITSYNC_SUPPORT}" "${OSCRIPT_VERSION}"

# интерактивное получение программной лицензии 1С через VNC (gitsync-движок):
# docker compose run --rm --service-ports converter license-gui
COPY docker/scripts/license-gui.sh /usr/local/bin/license-gui
RUN chmod +x /usr/local/bin/license-gui \
  # лицензия 1С живёт в /root/.1cv8 — персистим volume'ом v8home (compose)
  && mkdir -p /root/.1cv8

VOLUME ["/root/.1cv8"]

ENV PATH="/opt/1cv8/current:/opt/1C/1CE/components/1cedtcli:${JAVA_HOME}/bin:${PATH}"

COPY converter/ /opt/converter/

RUN printf '#!/bin/sh\nexec /opt/1cv8/current/ibcmd "$@"\n' > /usr/local/bin/ibcmd \
  && printf '#!/bin/sh\nexec /opt/1C/1CE/components/1cedtcli/1cedtcli "$@"\n' > /usr/local/bin/1cedtcli \
  && printf '#!/bin/sh\nexec env PYTHONPATH=/opt/converter python3 -m onec_convert "$@"\n' > /usr/local/bin/1c-convert \
  && chmod +x /usr/local/bin/ibcmd /usr/local/bin/1cedtcli /usr/local/bin/1c-convert \
  # 1cv8 (client) requires an X display even in DESIGNER batch mode — wrap it
  # with xvfb-run; v8find/gitsync/v8runner see the same executable path
  && mv /opt/1cv8/current/1cv8 /opt/1cv8/current/1cv8.real \
  && printf '#!/bin/sh\nexec xvfb-run -a /opt/1cv8/current/1cv8.real "$@"\n' > /opt/1cv8/current/1cv8 \
  && chmod +x /opt/1cv8/current/1cv8 \
  && mkdir -p /work/input /work/output /work/cache /var/1C/licenses \
  && 1c-convert selfcheck

WORKDIR /work

CMD ["bash"]
