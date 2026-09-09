# syntax=docker/dockerfile:1
#
# converter: хранилище 1С -> gitsync -> ibcmd -> EDT (1cedtcli) -> git monorepo.
#
# База — десктоп-слой mussolene/1c-develop (docs/research/06, docs/SPEC.md):
#   ghcr.io/mussolene/linux-desktop-base:bookworm = Xfce + Xvnc(:0, 5900) + xrdp + s6 + шрифты + ru_RU + gosu
#   + s6-сервисы xvfb/xfce/onec (onec/run мы заменяем своим — без onec-agent/desktop-иконок).
#
# Дистрибутивы 1С (закрытые) подаются через BuildKit named context `distr`
# (compose: build.additional_contexts.distr=./distr) и в образ не попадают:
#   - платформа 8.3.27: server64_8_3_27_*.zip (setup-full) или deb64_8_3_27_*.zip
#   - EDT offline:      1c_edt_distr_offline_*_linux_x86_64.tar.gz
# OneScript (публичный) скачивается с oscript.io при сборке.
#
# Два режима одного образа (docs/SPEC.md п.3.2):
#   license-ui: entrypoint /init (s6), ONEC_RUNTIME_MODE=license-ui, VNC 127.0.0.1:5900
#   converter:  entrypoint /opt/converter/entrypoint.sh (headless, без s6-сервисов)

ARG DESKTOP_BASE_IMAGE=ghcr.io/mussolene/linux-desktop-base:bookworm

# ------------------------------------------------------------- platform installer
FROM ${DESKTOP_BASE_IMAGE} AS platform-installer
ARG PLATFORM_COMPONENTS=server,client,ru

COPY docker/scripts/install-platform.sh /usr/local/sbin/onec-image/install-platform.sh

RUN --mount=type=bind,from=distr,source=.,target=/distr,readonly \
    bash /usr/local/sbin/onec-image/install-platform.sh /distr "${PLATFORM_COMPONENTS}" \
  && test -x /opt/1cv8/current/1cv8 \
  && test -x /opt/1cv8/current/ibcmd \
  && test -x /opt/1cv8/current/rac \
  && (getent group grp1cv8 >/dev/null 2>&1 || groupadd -r grp1cv8) \
  && mkdir -p /var/1C/licenses /var/log/1C /home/usr1cv8 \
  && chown root:grp1cv8 /var/1C/licenses && chmod 775 /var/1C/licenses \
  && chown -R usr1cv8:grp1cv8 /home/usr1cv8 /var/log/1C \
  && rm -rf /tmp/* /var/tmp/*

# ------------------------------------------------------------------------- EDT
FROM ${DESKTOP_BASE_IMAGE} AS edt-installer
ARG EDT_PLATFORM_SUPPORT=8.3.27
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64

COPY docker/scripts/install-edt.sh /usr/local/sbin/onec-image/install-edt.sh

RUN --mount=type=bind,from=distr,source=.,target=/distr,readonly \
    bash /usr/local/sbin/onec-image/install-edt.sh /distr "${EDT_PLATFORM_SUPPORT}" \
  && rm -rf /tmp/* /var/tmp/*

# ----------------------------------------------------------------------- final
FROM ${DESKTOP_BASE_IMAGE} AS converter
ARG PLATFORM_VERSION=unknown
ARG EDT_VERSION=unknown
ARG GITSYNC_VERSION=3.8.0
ARG OSCRIPT_VERSION=1.9.3
ARG REVISION=r1

LABEL org.opencontainers.image.title="1c-storage-to-edt" \
      org.opencontainers.image.description="1C storage -> gitsync -> ibcmd -> EDT (1cedtcli) -> git monorepo (base: mussolene/1c-develop)" \
      org.opencontainers.image.version="${PLATFORM_VERSION}+edt${EDT_VERSION}" \
      onec.converter.platform-version="${PLATFORM_VERSION}" \
      onec.converter.edt-version="${EDT_VERSION}" \
      onec.converter.gitsync-version="${GITSYNC_VERSION}" \
      onec.converter.revision="${REVISION}"

# git/ssh/unzip/rsync + Java 17 для 1cedtcli.
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      git \
      openssh-client \
      openjdk-17-jre-headless \
      procps \
      psmisc \
      rsync \
      unzip \
  && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64

# Платформа + EDT из installer-стадий (дистрибутивы в слой не попадают).
COPY --from=platform-installer /opt/1cv8 /opt/1cv8
COPY --from=edt-installer /opt/1C/1CE /opt/1C/1CE

ENV PATH="/opt/1cv8/current:/opt/1C/1CE/components/1cedtcli:${JAVA_HOME}/bin:${PATH}"

# OneScript 1.9.x (CI gitsync = 1.9.2; 2.x из 1c-develop не гарантирован для gitsync).
RUN curl -fsSL -o /tmp/oscript.deb \
      "https://oscript.io/downloads/${OSCRIPT_VERSION}/x64/onescript-engine_${OSCRIPT_VERSION}_all.deb" \
  || curl -fsSL -o /tmp/oscript.deb \
      "https://oscript.io/downloads/$(printf '%s' "${OSCRIPT_VERSION}" | tr '.' '_')/x64/onescript-engine_${OSCRIPT_VERSION}_all.deb" \
  && apt-get update \
  && apt-get install -y --no-install-recommends /tmp/oscript.deb \
  && rm -rf /var/lib/apt/lists/* /tmp/oscript.deb \
  && cfg="$(find /etc /usr/lib /usr/share -maxdepth 3 -name oscript.cfg 2>/dev/null | head -1)" \
  && if [ -n "$cfg" ]; then \
       if grep -q '^[[:space:]]*#*[[:space:]]*systemLanguage[[:space:]]*=' "$cfg"; then \
         sed -i 's/^[[:space:]]*#*[[:space:]]*systemLanguage[[:space:]]*=.*/systemLanguage = ru/' "$cfg"; \
       else \
         printf '\nsystemLanguage = ru\n' >> "$cfg"; \
       fi; \
     fi \
  && oscript -version

# gitsync + штатный пакет плагинов. Каталог плагинов фиксируем env, чтобы
# включённые на сборке плагины были видны под usr1cv8 в runtime.
ENV GITSYNC_PLUGINS_PATH=/opt/gitsync/plugins
RUN opm install "gitsync@${GITSYNC_VERSION}" \
  && gitsync plugins init \
  && gitsync plugins enable use-ibcmd edtExport limit check-authors \
  && gitsync plugins list \
  && mkdir -p /opt/gitsync/plugins \
  && chmod -R a+rX /opt/gitsync \
  && rm -rf /root/.local/share/ovm /tmp/* /var/tmp/*

# Наш s6-сервис onec (заменяет базовый: без onec-agent и desktop-иконок).
# Режимы: license-ui (1cv8c от usr1cv8 для активации), shell (idle).
COPY docker/rootfs/ /

# Runtime-каталоги конвейера.
RUN mkdir -p /repo /storage /cache /state /config \
  && chmod 775 /cache /state \
  && chown usr1cv8:grp1cv8 /cache /state /repo

# 1cv8 DESIGNER headless: фиктивный X на случай GUI-инициализации GTK-бинарня.
ENV DISPLAY=:99

COPY scripts/ /opt/converter/
RUN chmod +x /opt/converter/*.sh

# ENTRYPOINT /init (s6) остаётся от базы — для license-ui.
# converter в compose переопределяет entrypoint на /opt/converter/entrypoint.sh.
CMD ["sh", "-c", "echo 'Use: docker compose run --rm converter doctor|migrate|sync (или --profile license-ui up license-ui)'; exit 1"]
