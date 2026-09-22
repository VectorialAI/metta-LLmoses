"""Prevent native/overlay double definitions and silent entry-point bypasses."""
from pathlib import Path
import re
import unittest
from m2_test_support import ROOT

ADDITIVE={'utilities/general-helpers','scoring/bscore','moses/demo-problems',
          'moses/neighborhood-sampling'}
REQUIRED={'representation/add-logical-knobs','representation/build-logical',
          'representation/sample-logical-perms','scoring/cscore'}
ENTRIES=('boolean_state_test','boolean_pressure_test','expand-demes-test',
         'feature-selection-smoke-test','strategy_test','demos_test',
         'm2_merge_regression')


def imports(path):
    for line in path.read_text().splitlines():
        match=re.match(r'^\s*!\(import!\s+&self\s+([^\s)]+)',line)
        if match:
            yield match[1].strip('"')


def dependencies(path,seen=None):
    seen=set() if seen is None else seen
    if path in seen: return seen
    seen.add(path)
    for name in imports(path):
        if name.endswith('.py'): continue
        target=ROOT/(name if name.endswith('.metta') else name+'.metta')
        if target.exists(): dependencies(target,seen)
    return seen


class OverlayImports(unittest.TestCase):
    def test_entry_imports_choose_overlay_once(self):
        for entry in ENTRIES:
            seen=dependencies(ROOT/f'llmoses/llmoses-tests/{entry}.metta')
            relative={str(p.relative_to(ROOT))[:-6] for p in seen}
            with self.subTest(entry=entry):
                for name in relative:
                    if name.startswith('llmoses/'):
                        native=name[len('llmoses/'):]
                        if native not in ADDITIVE: self.assertNotIn(native,relative)
                for native in REQUIRED:
                    if native in relative or 'llmoses/'+native in relative:
                        self.assertIn('llmoses/'+native,relative)
                        self.assertNotIn(native,relative)

    def test_entry_metta_imports_exist(self):
        # Entry points use repository-root paths. Do not silently ignore a stale
        # import: PeTTa may continue until a consumer fails specialization.
        for entry in ENTRIES:
            path=ROOT/f'llmoses/llmoses-tests/{entry}.metta'
            for name in imports(path):
                if name.endswith('.py'): continue
                target=ROOT/(name if name.endswith('.metta') else name+'.metta')
                with self.subTest(entry=entry,dependency=name):
                    self.assertTrue(target.is_file(),f'missing import: {name}')

    def test_entry_imports_load_dependencies_before_consumers(self):
        order=(('scoring/strategy-score-cache','examples/tic-tac-toe/strategy-scoring'),
               ('scoring/cacheSpace','llmoses/scoring/complexity-based-scorer'),
               ('llmoses/wrapper/extractors','llmoses/optimization/hill-climbing-helpers'),
               ('llmoses/wrapper/extractors','llmoses/wrapper/state-builder'),
               ('llmoses/wrapper/state-builder','llmoses/deme/expand-deme'))
        for entry in ENTRIES:
            names=list(imports(ROOT/f'llmoses/llmoses-tests/{entry}.metta'))
            for dependency,consumer in order:
                if consumer not in names: continue
                with self.subTest(entry=entry,consumer=consumer):
                    self.assertIn(dependency,names)
                    self.assertLess(names.index(dependency),names.index(consumer))



if __name__=='__main__':
    unittest.main()
