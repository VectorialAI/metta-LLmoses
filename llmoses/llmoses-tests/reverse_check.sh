#!/usr/bin/env bash
# Deferred non-vacuity checks. Mutations are confined to this script's temp copy.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../.." && pwd)
python3 - "$REPO" <<'PY'
from pathlib import Path
import shutil,subprocess,sys,tempfile
repo=Path(sys.argv[1])
modules=['lever_policy_test','lever_wiring_test','scoring_test','silent_failure_test',
         'atom_evidence_test','response_template_test','resolution_regression_test',
         'hardening_unit_test']
baseline=subprocess.run([sys.executable,'-m','unittest',*modules],cwd=repo/'llmoses/llmoses-tests')
if baseline.returncode: raise SystemExit('baseline failed; refusing a vacuous reverse check')
mutants=[
    ('absolute offsets','lever_policy.py','score + offsets.get(i, 0.0)','offsets.get(i, 0.0)', 'lever_policy_test'),
    ('off gate','lever_policy.py','if b == 0:','if False:', 'lever_policy_test'),
    ('token leak','state_builder.py','buffer = _combo_bufs.pop(int(_num(token)))',
     'buffer = _combo_bufs[int(_num(token))]', 'resolution_regression_test'),
    ('ratio<=0 ceiling','state_builder.py',
     'return min(1.0, max(0.0, 1.0 / r)) if r > 0 else 1.0',
     'return min(1.0, max(0.0, 1.0 / r)) if r > 0 else 0.0', 'scoring_test'),
    ('rowweight raw mix','state_builder.py',
     'preference = policy.normalize([utilities.get(i, 1.0) for i in range(count)], prior)',
     'preference = [utilities.get(i, 1.0) for i in range(count)]', 'lever_wiring_test'),
    ('unknown emit section','state_builder.py',
     '_abort_run("unknown_emit_section", unknown=sorted(unknown), allowed=list(_EMITTABLE_SECTIONS))',
     'return names | unknown', 'silent_failure_test'),
    ('lossless default off','atom_evidence.py',
     'return evidence, lossless, rollup',
     'return evidence, None, rollup', 'atom_evidence_test'),
]
for label,name,old,new,module in mutants:
    with tempfile.TemporaryDirectory(prefix='llmoses-m2-reverse-') as directory:
        root=Path(directory)
        for section in ('utilities','llmoses-tests','configs','skills','agent-configs'):
            shutil.copytree(repo/'llmoses'/section,root/'llmoses'/section,
                            ignore=shutil.ignore_patterns('__pycache__','outputs'))
        path=root/'llmoses/utilities'/name
        source=path.read_text()
        if source.count(old)!=1: raise SystemExit('mutation target changed: '+label)
        path.write_text(source.replace(old,new))
        result=subprocess.run([sys.executable,'-m','unittest',module],cwd=root/'llmoses/llmoses-tests',
                              text=True,capture_output=True,timeout=60)
        if result.returncode==0: raise SystemExit('surviving mutant: '+label)
        print('detected:',label)
PY
