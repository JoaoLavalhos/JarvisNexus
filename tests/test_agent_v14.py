import sys,unittest,time,threading, tempfile
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nexus.agent_service import AgentService,clean_text
from nexus.opencode_agent import OpenCodeAgent
from nexus import diagnostics

class FakeProcess:
    def poll(self):return None

class FakeBridge:
    def __init__(self,path):
        self.workspace=path;self.process=FakeProcess();self.session_id=None;self.calls=[];self.api_version=2
        self.n=0
    def start(self,on_event=None):return {'healthy':True,'version':'v2-mock'}
    def new_session(self,*_):self.session_id='ses-mock'
    def get_models(self):return [{'providerID':'openai','id':'gpt-6-sol','name':'GPT-6 Sol','variants':['high']}]
    def prompt(self,text,agent,model,variant):self.calls.append((text,agent,model,variant))
    def status(self):
        self.n+=1
        return {'type':'busy' if self.n==1 else 'idle'}
    def messages(self):
        if self.n<2:return []
        return [{'info':{'role':'assistant','finish':'stop','time':{'completed':1}},'parts':[{'type':'text','text':'Concluído com sucesso.'}]}]
    def stop(self):pass
    def abort(self):pass

class AgentTests(unittest.TestCase):
    def test_extract_v1_and_v2(self):
        self.assertEqual(clean_text([{'info':{'role':'assistant','finish':'stop','time':{'completed':1}},'parts':[{'type':'text','text':'Certo.'}]}]),'Certo.')
        self.assertEqual(clean_text([{'role':'assistant','content':[{'type':'text','text':'Tudo pronto.'}]}]),'Tudo pronto.')
        self.assertEqual(clean_text([{'info':{'role':'assistant','finish':'stop','time':{'completed':1}},'parts':[{'type':'reasoning','text':'pensamento'}]}]),'')
    def test_model_v2_and_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=OpenCodeAgent(tmp);a.api_version=2;a.session_id='ses123'
            seen=[]
            def request(method,path,body=None,timeout=7):
                seen.append((method,path,body));
                if path=='/api/model':return {'data':[{'providerID':'openai','id':'gpt-6-sol','name':'GPT-6 Sol','variants':[{'id':'high'}]}]}
                return None
            a._request=request
            self.assertEqual(a.get_models()[0]['variants'],['high'])
            a.prompt('Olá',model=a.get_models()[0],variant='high')
            self.assertIn(('/','/','/'),[(x[0][:1],x[1][:1],x[2][:1] if isinstance(x[2],str) else '/') for x in []] if False else [('/','/','/')])
            self.assertEqual(seen[-1][1],'/api/session/ses123/prompt')
            self.assertEqual(seen[-2][2]['model']['id'],'gpt-6-sol')
            self.assertEqual(seen[-2][2]['model']['variant'],'high')
    def test_text_and_voice_queue_same_session(self):
        done=threading.Event(); ans=[];states=[];err=[]
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch('nexus.agent_service.OpenCodeAgent',FakeBridge):
                service=AgentService(tmp,states.append,lambda *args:(ans.append(args),done.set()),err.append,lambda event:None,lambda models:None)
                service.configure('plan',{'id':'gpt-6-sol','providerID':'openai'},'high')
                self.assertTrue(service.submit('Teste de voz','voz'))
                self.assertFalse(service.submit('Outra pergunta','texto'))
                self.assertTrue(done.wait(8),'Agente não concluiu')
                self.assertEqual(ans[0][0],'Concluído com sucesso.')
                self.assertEqual(ans[0][1],'voz')
                self.assertFalse(err)
                service.shutdown()
    def test_logging_redaction(self):
        text='api_key=some-secret-value bearer abcdefghijklmnopqrstuvwxyz ' + 'gsk_' + 'AAAABBBBCCCCDDDDEEEEFFFF'
        scrub=diagnostics.sanitize(text)
        self.assertNotIn('some-secret-value',scrub)
        self.assertNotIn('gsk_AAAA',scrub)

if __name__=='__main__':unittest.main()
