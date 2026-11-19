#!/usr/bin/env bash
# Executes RUBRIC-IV2-RG4 probes (a, b, c', d) on one run dir. Usage: probes-rg4.sh <run-dir>
RUN="$1"; S=$(mktemp -d); cp -R "$RUN" "$S/repo" && cd "$S/repo" || exit 1
rm -rf cache output/report.json output/report.html
echo "== probe-a"
python3 -B reportgen.py >/dev/null 2>&1; echo "base-exit=$?"
python3 - <<'PY' 2>/dev/null
import json
p="cache/state.json"; s=json.load(open(p))
e=s["small_transactions.csv"]; e["registry_version"]="1"; e["summary"]["columns"]["merchant"]["distinct"]=99
json.dump(s, open(p,"w"))
PY
python3 -B reportgen.py >/dev/null 2>&1
python3 -B -c "import json; r=json.load(open('output/report.json')); print('merchant.distinct=%s' % r['files']['small_transactions.csv']['summary']['columns']['merchant']['distinct'])" 2>&1 | tail -1
echo "== probe-b"
rm -rf cache; rm -f output/report.json output/report.html
python3 -B reportgen.py >/dev/null 2>&1 && cp output/report.json "$S/cold.json"
python3 -B reportgen.py >/dev/null 2>&1 && cp output/report.json "$S/warm.json"
diff -q "$S/cold.json" "$S/warm.json" >/dev/null && echo REPORTS-IDENTICAL || echo REPORTS-DIFFER
python3 -B -c "import json; r=json.load(open('output/report.json')); print('generated_from=%s' % r['files']['small_devices.csv']['generated_from'])" 2>&1 | tail -1
echo "== probe-c"
cd "$S/repo"; rm -rf cache output/report.json output/report.html
W='import builtins, io, os, sys
c=[]; ro=io.open
def w(f,*a,**k):
    if os.path.basename(str(f))=="rules.example.toml": c.append(str(f))
    return ro(f,*a,**k)
io.open=w; builtins.open=w
sys.path.insert(0,os.getcwd()); import reportgen
reportgen.main(["--rules","rules.example.toml","--input","input","--output","'"$S"'/outc","--cache","'"$S"'/cc.json"])
print("rules_opens=%d" % len(c))'
python3 -B -c "$W" 2>/dev/null | tail -1
echo "== probe-d (policy A)"
rm -rf cache output/report.json output/report.html
python3 -B reportgen.py >/dev/null 2>&1; b=$?
if [ "$b" -ne 0 ] || [ ! -f output/report.json ] || [ ! -f cache/state.json ]; then echo BASELINE-FAILED; exit 0; fi
sha() { shasum -a 256 output/report.json output/report.html cache/state.json 2>/dev/null; }
before=$(sha)
printf 'tx_id,merchant,amount,date,share\nx1,Bad,see invoice,01/01/2026,0.5\n' > input/bad_payments.csv
python3 -B reportgen.py >/dev/null 2>&1; echo "exit=$?"
rm input/bad_payments.csv
after=$(sha)
test "$before" = "$after" && echo PREVIOUS-OUTPUT-AND-STATE-INTACT || echo PREVIOUS-OUTPUT-OR-STATE-CHANGED
rm -rf "$S"
