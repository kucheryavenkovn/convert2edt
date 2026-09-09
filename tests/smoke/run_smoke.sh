#!/usr/bin/env bash
# Smoke test: CF -> XML -> EDT -> XML -> CF entirely inside Linux Docker
# (ibcmd + 1cedtcli, no DESIGNER, no Windows, no Host Bridge).
#
# Usage (inside the converter container):
#   1c-convert smoke            # default fixture /work/tests/fixtures/1Cv8.cf
#   1c-convert smoke <file.cf>
#
# The final CF is verified by loading it into a fresh temporary infobase
# (platform readability check). Binary equality of CF files is not expected.
set -euo pipefail

SRC_CF="${1:-/work/tests/fixtures/1Cv8.cf}"
OUT="${SMOKE_OUT:-/work/output/smoke}"

echo "=== 1C converter smoke test ==="
echo "source : $SRC_CF"
echo "output : $OUT"

rm -rf "$OUT"
mkdir -p "$OUT"

echo
echo "--- [0/6] info ---"
1c-convert info

echo
echo "--- [1/6] CF -> XML ---"
1c-convert cf-to-xml "$SRC_CF" "$OUT/xml1"

echo
echo "--- [2/6] XML -> EDT ---"
1c-convert xml-to-edt "$OUT/xml1" "$OUT/edt"

echo
echo "--- [3/6] EDT -> XML ---"
1c-convert edt-to-xml "$OUT/edt" "$OUT/xml2"

echo
echo "--- [4/6] XML -> CF ---"
1c-convert xml-to-cf "$OUT/xml2" "$OUT/result.cf"

echo
echo "--- [5/6] result CF readability (load into a fresh infobase) ---"
1c-convert cf-to-xml "$OUT/result.cf" "$OUT/xml3"

echo
echo "--- [6/6] artifacts ---"
for marker in \
  "$OUT/xml1/Configuration.xml" \
  "$OUT/edt/.project" \
  "$OUT/edt/src/Configuration/Configuration.mdo" \
  "$OUT/xml2/Configuration.xml" \
  "$OUT/result.cf" \
  "$OUT/xml3/Configuration.xml"; do
  test -e "$marker"
  echo "  OK  $marker"
done

SIZE="$(stat -c '%s' "$OUT/result.cf")"
echo
echo "SMOKE OK: result.cf = $SIZE bytes, readable by the platform."
