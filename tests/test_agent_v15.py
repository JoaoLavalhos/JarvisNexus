import unittest
from pathlib import Path
from unittest.mock import patch
import sys
import tempfile
import types
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nexus.agent_service import (clean_text, _assistant_message_id,
    fresh_assistant_answer, is_brief_conversation, AgentService)


def message(role, msg_id, text):
    return {'info': {'role':role, 'id':msg_id, 'finish':'stop', 'time':{'completed':1}},
            'parts':[{'type':'text','text':text}]}

class FakeProcess:
    def poll(self):return None

class FakeBridge:
    def __init__(self):
        self.session_id='S1';self.process=FakeProcess();self.requests=[]
        self._messages=[message('user','u1','quem é você?'),
                       message('assistant','a1','Sou o GPT-6 Sol, da OpenAI.')]
    def messages(self):return list(self._messages)
    def prompt(self,text,agent,model,variant):
        self.requests.append((text,agent,model,variant))
        self._messages.append(message('user','u2',text))
        self._messages.append(message('assistant','a2',
                                      'Sim, senhor. Recebi sua fala pelo microfone.'))
    def status(self):return {'type':'idle'}
    def stop(self):pass

class TestV15(unittest.TestCase):
    def test_never_reuse_previous_reply_on_new_user(self):
        old=message('assistant','a1','Sou o GPT-6 Sol.')
        baseline={_assistant_message_id(old)}
        messages=[old,message('user','u2','Consegue me ouvir?')]
        self.assertEqual(fresh_assistant_answer(messages,baseline),('',None))
    def test_accept_only_current_assistant(self):
        old=message('assistant','a1','Sou o GPT-6 Sol.')
        new=message('assistant','a2','Sim, estou ouvindo, senhor.')
        baseline={_assistant_message_id(old)}
        self.assertEqual(fresh_assistant_answer([old,message('user','u2','Oi'),new],baseline)[0],
                         'Sim, estou ouvindo, senhor.')
    def test_short_conversation_is_conservative(self):
        for text in ('Consegue me ouvir?', 'Jarvis, alô', 'Oi', 'Bom dia', 'Quem é você?', 'Alô, tá me ouvindo?', 'Você consegue me ouvir?'):
            with self.subTest(text=text):self.assertTrue(is_brief_conversation(text))
        for text in ('Jarvis, abra o navegador','Analise meu código',
                     'Qual a previsão do tempo de amanhã?',
                     'Encontre o bug e corrija o arquivo'):
            with self.subTest(text=text):self.assertFalse(is_brief_conversation(text))
    def test_agent_responses_not_recycled_and_gpt_is_active(self):
        service=AgentService(tempfile.gettempdir(),lambda x:None,
                             lambda a,b,c:self.answers.append((a,b,c)),
                             lambda x:self.errors.append(x),lambda x:None,lambda x:None)
        self.answers=[];self.errors=[]
        bridge=FakeBridge();service.bridge=bridge
        model={'name':'GPT-6 Sol','id':'gpt-6-sol','providerID':'openai','variants':['low','high']}
        service.configure('plan',model,'high',quick_chat=True)
        with patch('nexus.agent_service.time.sleep',return_value=None):
            service._run('Consegue me ouvir?','plan',model,'high','voz',True)
        self.assertFalse(self.errors)
        self.assertEqual(len(self.answers),1)
        self.assertEqual(self.answers[0][0],'Sim, senhor. Recebi sua fala pelo microfone.')
        self.assertEqual(bridge.requests[0][3],'low')
        self.assertIn('Não mencione câmera',bridge.requests[0][0])
        self.assertIn('JARVIS NEXUS',bridge.requests[0][0])
        service.shutdown()
    def test_long_task_preserves_high(self):
        service=AgentService(tempfile.gettempdir(),lambda x:None,lambda a,b,c:None,
                             lambda x:self.fail(x),lambda x:None,lambda x:None)
        bridge=FakeBridge();service.bridge=bridge
        model={'name':'GPT-6 Sol','id':'gpt-6-sol','providerID':'openai','variants':['low','high']}
        with patch('nexus.agent_service.time.sleep',return_value=None):
            service._run('Analise o projeto e corrija erros','build',model,'high','texto',True)
        self.assertEqual(bridge.requests[0][3],'high')
        service.shutdown()
if __name__=='__main__':unittest.main(verbosity=2)
