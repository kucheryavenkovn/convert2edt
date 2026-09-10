#!/usr/bin/env bash
# Сборка ctool1cd.exe (Windows x64, mingw, статический boost) из upstream
# e8tools/tool1cd — включает depot ver100 (PR #295).
# Пин коммита можно переопределить: CONVERT_CTOOL1CD_REF=<sha>
set -eux
export PATH="/mingw64/bin:$PATH"
REF="${CONVERT_CTOOL1CD_REF:-625ac1a47b6ed63bba2848842daf1909813f84d4}"
cd /tmp
rm -rf tool1cd-src tool1cd-${REF}*
curl -fsSL "https://github.com/e8tools/tool1cd/archive/${REF}.tar.gz" | tar -xz
mv tool1cd-${REF}* tool1cd-src
cd tool1cd-src
mkdir build && cd build
cmake .. -G "MinGW Makefiles" -DNOGUI=ON -DCMAKE_BUILD_TYPE=Release
mingw32-make -j"$(nproc)" 2>&1 | tail -5
find . -name 'ctool1cd.exe' -exec cp {} /out/ \;
# рантайм-библиотеки mingw (остальное слинковано статически)
for dll in libwinpthread-1.dll zlib1.dll; do
  cp "/mingw64/bin/$dll" /out/ 2>/dev/null || true
done
ls -la /out/
