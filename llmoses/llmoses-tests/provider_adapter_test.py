"""Provider classification, schema propagation, and subprocess failures (offline)."""
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch
from m2_test_support import config
import provider_adapter as pa


class ProviderAdapter(unittest.TestCase):
    def test_whole_stderr_classification(self):
        for text,klass,retry in [('401 Unauthorized','auth',False),
                ('429 insufficient_quota','quota',False),('429 Too Many Requests','rate_limit',True),
                ('stream disconnected before completion','network',True),('502 Bad Gateway','server',True),
                ('invalid output schema','configuration',False),('unknown failure','provider_error',False)]:
            with self.subTest(klass=klass):
                err=pa.classify('warning '*700+text,1)
                self.assertEqual((err.error_class,err.retryable),(klass,retry))
                self.assertEqual(pa.status_for(klass),503)

    def test_command_gets_schema_and_closed_stdin(self):
        with tempfile.TemporaryDirectory(prefix='llmoses-provider-test-') as directory:
            script=Path(directory)/'provider.py'
            script.write_text("import json, os, sys\nprompt=sys.stdin.read()\nschema=json.load(open(os.environ['LLMOSES_OUTPUT_SCHEMA_PATH']))\nassert prompt=='question' and schema['type']=='object'\nprint('{}')\n")
            command=shlex.join([sys.executable,str(script)])
            with patch.dict(os.environ,{'LLMOSES_LIVE_CMD':command}):
                result=pa.invoke('question','unused','unused',2,{'type':'object'})
            self.assertEqual(json.loads(result),{})

    def test_timeout_and_missing_binary_surface_structured_error(self):
        with self.assertRaises(pa.ProviderError) as caught:
            pa._run(['/definitely/not/a/provider'], '', 1, None, dict(os.environ))
        self.assertEqual(pa.status_for(caught.exception.error_class),503)
        with self.assertRaises(pa.ProviderError) as caught:
            pa._run([sys.executable,'-c','import time; time.sleep(2)'],'',.01,None,dict(os.environ))
        self.assertEqual(caught.exception.error_class,'timeout')


if __name__=='__main__':
    unittest.main()
