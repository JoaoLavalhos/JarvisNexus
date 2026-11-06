"""New V1.7 regression tests; no network, microphone, credentials, or screen capture."""
from __future__ import annotations
import base64
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import tempfile
import unittest
from unittest.mock import patch
from nexus.opencode_agent import OpenCodeAgent,AgentError
from nexus.agent_screen import explicit_screen_request
from nexus.agent_activity import normalize_event, ActivityLedger
from nexus.agent_service import AgentService

class TestV17(unittest.TestCase):
    def test_explicit_screen_requests_only(self):
        for t in ('Jarvis, olhe minha tela', 'Analise o que aparece na minha tela',
                  'Faça um print da tela', 'Olha a tela por favor'):
            self.assertTrue(explicit_screen_request(t), t)
        for t in ('Está chovendo?', 'Qual a tela de login?', 'Tá vendo a pasta teste 1?',
                  'Analise os arquivos do projeto'):
            self.assertFalse(explicit_screen_request(t), t)

    def test_v2_screen_image_file_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent=OpenCodeAgent(tmp);agent.session_id='s';agent.api_version=2
            calls=[]
            agent._request=lambda method,path,body=None,timeout=7: calls.append((method,path,body))
            agent.prompt('Analise esta tela',agent='plan',image=b'\xff\xd8\xfftest')
            payload=calls[-1][2]
            self.assertEqual(payload['text'],'Analise esta tela')
            self.assertTrue(payload['files'][0]['uri'].startswith('data:image/jpeg;base64,'))
            self.assertEqual(base64.b64decode(payload['files'][0]['uri'].split(',',1)[1]),b'\xff\xd8\xfftest')
            self.assertEqual(payload['files'][0]['source'],{'type':'inline'})
            calls.clear()
            agent.prompt('Pergunta simples',agent='plan')
            self.assertNotIn('files',calls[-1][2])

    def test_capture_above_three_megabytes_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent=OpenCodeAgent(tmp);agent.session_id='s';agent.api_version=2
            agent._request=lambda *x,**kw:None
            with self.assertRaises(AgentError):
                agent.prompt('olhe',image=b'x'*3000001)

    def test_v2_tools_and_event_details(self):
        event=normalize_event({'type':'session.tool.called', 'data':{
            'sessionID':'s', 'id':'tool123','toolCall':{
                'name':'shell','input':{'command':'Get-ChildItem -Name'}}}})
        self.assertIn('shell',event['label'])
        self.assertIn('Get-ChildItem',event['detail'])
        ledger=ActivityLedger();ledger.begin('s')
        ledger.receive({'type':'session.execution.started','data':{'sessionID':'s'}})
        self.assertEqual(ledger.state(),'EXECUTANDO')

    def test_runtime_configurable_and_not_180(self):
        svc=AgentService(tempfile.gettempdir(),lambda _:None,
          lambda *args:None,lambda x:None,lambda _:None,lambda _:None)
        self.assertGreaterEqual(svc._max_runtime_sec,300)
        svc.shutdown()

if __name__=='__main__':unittest.main(verbosity=2)
