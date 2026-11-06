"""V1.6 regressions: failures must be visible, never reported as successful."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import unittest
import tempfile
from unittest.mock import patch
from nexus.agent_activity import normalize_event,ActivityLedger
from nexus.agent_service import AgentService

class FakeProcess:
    def poll(self):return None

class FakeBridge:
    def __init__(self):
        self.session_id='s-v16'
        self.process=FakeProcess()
        self._messages=[]
        self.events=[]
    def messages(self):return list(self._messages)
    def prompt(self,text,agent,model,variant,image=None):
        self._messages.extend([
           {'info':{'id':'user2','role':'user'}, 'parts':[{'type':'text','text':text}]},
           {'info':{'id':'assistant2','role':'assistant'},
              'parts':[{'type':'text','text':'Vou verificar os arquivos agora.'}]},
        ])
        for raw in self.events:
            if self.callback:self.callback(raw)
    def status(self):return {'type':'idle'}
    def stop(self):pass
    callback=None

class TestV16(unittest.TestCase):
    def test_permission_denied_is_explained(self):
        ev=normalize_event({'type':'permission.rejected','properties':{'sessionID':'abc',
          'error':{'type':'permission.rejected','message':'Permission denied: external_directory'}}})
        self.assertTrue(ev['blocked'])
        self.assertIn('pasta',ev['detail'].lower())

    def test_activity_state_blocked(self):
        led=ActivityLedger();led.begin('s-v16')
        led.receive({'type':'session.tool.called','properties':{'sessionID':'s-v16','tool':'read'}})
        led.receive({'type':'permission.rejected','properties':{'sessionID':'s-v16',
                        'message':'Permission denied: external_directory'}})
        self.assertEqual(led.state(),'BLOQUEADO')
        self.assertTrue(led.summary()['failures'])

    def test_stray_session_events_ignored(self):
        led=ActivityLedger();led.begin('current')
        self.assertIsNone(led.receive({'type':'permission.rejected',
                         'properties':{'sessionID':'other','message':'no'}}))
        self.assertFalse(led.summary()['failures'])

    def test_preamble_cannot_count_as_completed_on_permission_rejection(self):
        answers=[];errors=[]
        svc=AgentService(tempfile.gettempdir(),lambda _:None,
             lambda *args:answers.append(args),lambda err:errors.append(err),lambda _:None,lambda _:None)
        b=FakeBridge();svc.bridge=b
        b.callback=svc._handle_event
        b.events=[{'type':'permission.rejected','properties':{'sessionID':'s-v16',
                  'message':'Permission denied: external_directory'}}]
        with patch('nexus.agent_service.time.sleep',return_value=None):
            svc._run('Veja outra pasta','plan',None,'high','voz',False)
        self.assertFalse(answers)
        self.assertTrue(errors)
        self.assertIn('BLOQUEADA',errors[0])
        svc.shutdown()

    def test_v2_tool_name_resolves_across_events(self):
        led=ActivityLedger();led.begin('s-v16')
        led.receive({'type':'session.tool.input.started',
                    'data':{'sessionID':'s-v16','id':'call-1','name':'bash'}})
        event=led.receive({'type':'session.tool.called',
                    'data':{'sessionID':'s-v16','id':'call-1','input':{'command':'echo test'},'executed':True}})
        self.assertIn('bash',event['label'])
        self.assertIn('echo test',event['detail'])

    def test_tool_success_after_failure_requires_terminal_success_event(self):
        led=ActivityLedger();led.begin('s-v16')
        led.receive({'type':'session.tool.failed','properties':{'sessionID':'s-v16',
                     'tool':'read','error':'arquivo indisponível'}})
        led.receive({'type':'session.execution.succeeded','properties':{'sessionID':'s-v16'}})
        self.assertTrue(led.summary()['completed'])
        self.assertEqual(len(led.summary()['failures']),1)

if __name__=='__main__': unittest.main(verbosity=2)
