"""Configuration validation, rendered run guides and pinned protocol coverage."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from m2_test_support import config, ROOT
import context_docs
import lever_config
import protocol_version


class Configuration(unittest.TestCase):
    def test_explicit_temperature_and_retired_controls(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(ValueError): lever_config.load()
        with patch.dict(os.environ,{'LLMOSES_SELECTION_TEMPERATURE':'25'},clear=True):
            self.assertEqual(lever_config.load()['selection_temperature'],25)
        with patch.dict(os.environ,{'LLMOSES_SELECTION_TEMPERATURE':'25',
                                    'LLMOSES_APPLY_LEVERS':'comparator'},clear=True):
            with self.assertRaises(ValueError): lever_config.load()

    def test_declared_controls_are_closed_finite_and_clamped(self):
        with tempfile.TemporaryDirectory(prefix='llmoses-config-test-') as directory:
            path=Path(directory)/'config.json'
            for delta in ({'context_radius':4},{'rule_budget':True},{'levers':{'ratio':{'b':1}}},
                          {'levers':{'atom':{'b':float('nan')}}},{'mode':'masks'}):
                path.write_text(json.dumps({'selection_temperature':100,**delta}))
                with patch.dict(os.environ,{},clear=True):
                    with self.assertRaises(ValueError): lever_config.load(str(path))
            path.write_text(json.dumps({'selection_temperature':100,'complexity_coef':2}))
            with patch.dict(os.environ,{},clear=True):
                self.assertEqual(lever_config.load(str(path))['complexity_coef'],1)

    def test_run_guides_render_experiment_parameters(self):
        with tempfile.TemporaryDirectory(prefix='llmoses-guides-test-') as directory:
            context_docs.ensure_run_context(directory,'example',1,'boolean',
                {'input_labels':['X1','X2']},['atom'],experiment=config())
            text=(Path(directory)/'run-instructions.md').read_text()
            self.assertIn('context_radius',text)
            self.assertIn('delta_max',text)
            self.assertIn('step-G-call-C',text)
            self.assertNotIn('{experiment_json}',text)

    def test_protocol_covers_changed_contract_and_overlay(self):
        names={str(Path(p).relative_to(ROOT/'llmoses')) for p in protocol_version.covered_files()}
        for expected in ('utilities/call_paths.py','utilities/conditional_policy.py',
                         'utilities/atom_evidence.py','representation/build-logical.metta',
                         'scoring/cscore.metta','skills/UTILITY_RESPONSE.md'):
            self.assertIn(expected,names)
        with patch.dict(os.environ,{'LLMOSES_PROTOCOL_PIN':'wrong'}):
            with self.assertRaises(protocol_version.ProtocolPinError): protocol_version.check_pin()


if __name__=='__main__':
    unittest.main()
