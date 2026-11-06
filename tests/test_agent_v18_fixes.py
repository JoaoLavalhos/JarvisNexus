"""Regressions from the user's real V18 logs on 2026-11-04."""
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import types
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtWidgets import QApplication
from nexus.agent_screen import explicit_screen_request
from nexus.agent_progress import ExecutionProgress
from nexus.agent_verification import requested_lines,paths_from_input,verify_lines,file_instruction
from nexus.agent_service import AgentService
from nexus.opencode_agent import OpenCodeAgent,AgentError
from nexus.agent_voice import PCMPlayer
from nexus import diagnostics as diag

class ProgressAndFiles(unittest.TestCase):
    def test_real_voice_requests_trigger_capture(self):
        for text in ['Fala aí, tu consegue ver minha tela?','Me diga aí Jarvis, tu consegue ver minha tela?',
                     'Você está vendo minha tela?','Pode visualizar meu monitor?']:
            with self.subTest(text=text):self.assertTrue(explicit_screen_request(text))
        for text in ['Não envie a minha tela','Como limpar uma tela de computador?','Não quero que capture minha tela']:
            with self.subTest(text=text):self.assertFalse(explicit_screen_request(text))

    def test_long_patch_preparation_is_visible_without_exposing_reasoning(self):
        tick=[0.0];progress=ExecutionProgress(clock=lambda:tick[0])
        progress.observe({'type':'session.tool.input.started','data':{'id':'p','name':'patch'}})
        for i in range(5):
            tick[0]+=1
            sample=progress.observe({'type':'session.tool.input.delta','data':{'id':'p','delta':'test code'}})
        self.assertEqual(progress.snapshot()['characters'],45)
        self.assertIn('patch',progress.description());self.assertEqual(progress.snapshot()['silent_seconds'],0)
        self.assertEqual(sample['properties']['characters'],45)
        self.assertNotIn('test code',json.dumps(sample))
        progress.observe({'type':'session.reasoning.delta','data':{'delta':'private model thought'}})
        self.assertNotIn('private model thought',json.dumps(progress.snapshot()))
        tick[0]+=125;self.assertEqual(progress.snapshot()['silent_seconds'],125)

    def test_pending_permission_does_not_look_like_generating_patch(self):
        progress=ExecutionProgress();progress.observe({'type':'permission.asked','properties':{'id':'permission'}})
        self.assertEqual(progress.snapshot()['phase'],'waiting_permission')
        self.assertIn('autorização',progress.description())

    def test_parallel_tool_finish_does_not_hide_pending_permission(self):
        progress=ExecutionProgress()
        progress.observe({'type':'session.tool.input.started','data':{'id':'read','name':'read'}})
        progress.observe({'type':'permission.asked','properties':{'id':'p'}})
        progress.observe({'type':'session.tool.success','data':{'id':'read'}})
        self.assertEqual(progress.snapshot()['phase'],'waiting_permission')
        progress.observe({'type':'permission.replied','properties':{'id':'p'}})
        self.assertNotEqual(progress.snapshot()['phase'],'waiting_permission')

    def test_line_count_is_verified_from_actual_file(self):
        with tempfile.TemporaryDirectory() as directory:
            page=Path(directory)/'page.html';page.write_text('<html>\n<body>\n</body>\n</html>\n',encoding='utf-8')
            evidence,error=verify_lines(1000,[page])
            self.assertIn('4 linhas',error);self.assertEqual(evidence[0]['lines'],4)
            page.write_text('\n'.join(f'<p>Produto {i}</p>' for i in range(1000))+'\n',encoding='utf-8')
            evidence,error=verify_lines(1000,[page]);self.assertIsNone(error);self.assertEqual(evidence[0]['lines'],1000)

    def test_request_and_tool_paths(self):
        self.assertEqual(requested_lines('faça um HTML dentro dele com 1000 linhas sobre cacau show'),1000)
        self.assertEqual(requested_lines('altere o site para ter mil linhas'),1000)
        self.assertIsNone(requested_lines('esse arquivo tem mil linhas?'))
        self.assertIn('pequeno script',file_instruction('crie um HTML de 1000 linhas'))
        candidates=paths_from_input({'command':"Get-Content -LiteralPath 'C:\\Users\\Usuario\\Desktop\\Teste 1\\cacaushow_longo.html' -Raw"},Path.cwd())
        self.assertTrue(any(p.name=='cacaushow_longo.html' for p in candidates))

    def test_diagnostic_event_field_does_not_crash(self):
        diag.warning('opencode.event',event='session.tool.failed',details='synthetic failure')

    def test_retry_does_not_reuse_previous_execution_success(self):
        from nexus.agent_activity import ActivityLedger
        ledger=ActivityLedger();ledger.begin('s')
        ledger.receive({'type':'session.execution.succeeded','data':{'sessionID':'s'}})
        self.assertTrue(ledger.summary()['completed'])
        ledger.begin('s',preserve=True)
        ledger.receive({'type':'session.step.ended','data':{'sessionID':'s'}})
        self.assertFalse(ledger.summary()['completed'])

    def test_shell_exit_one_is_visible_failure_even_when_tool_transport_succeeds(self):
        from nexus.agent_activity import normalize_event
        item=normalize_event({'type':'session.tool.success','data':{'id':'cmd','metadata':{'exit':1},'content':[{'type':'text','text':'SyntaxError'}]}})
        self.assertTrue(item['failure']);self.assertEqual(item['exit_code'],1)
        self.assertIn('código 1',item['label'])

    def test_image_receipt_must_match_new_message_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge=OpenCodeAgent(directory);data=b'synthetic-image-content'
            bridge.messages=lambda:[{'id':'old','type':'user','files':[{'data':base64.b64encode(b'old').decode(),'mime':'image/jpeg'}]},
                {'id':'new','type':'user','files':[{'data':base64.b64encode(data).decode(),'mime':'image/jpeg'}]}]
            receipt=bridge.verify_image_attachment(data,{'old'})
            self.assertEqual(receipt['message_id'],'new');self.assertEqual(receipt['bytes'],len(data))
            with self.assertRaises(AgentError):bridge.verify_image_attachment(b'different',{'old','new'},timeout=0)

class LocalGeneratorAndQuestions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_generator_preserves_catalog_creates_backup_and_exact_nonempty_lines(self):
        from nexus.html_builder import build
        with tempfile.TemporaryDirectory() as directory:
            page=Path(directory)/'catalogo.html'
            source='<html><head><title>Cacau Show</title></head><body><div class="product"><p>Trufa Tradicional</p><p class="price">R$ 5,00</p></div></body></html>'
            page.write_text(source,encoding='utf-8')
            result=build(page,1000);rendered=page.read_text(encoding='utf-8')
            self.assertEqual(len(rendered.splitlines()),1000)
            self.assertTrue(all(line.strip() for line in rendered.splitlines()))
            self.assertIn('Trufa Tradicional',rendered);self.assertIn('R$ 5,00',rendered)
            self.assertEqual(Path(result['backup']).read_text(encoding='utf-8'),source)
            self.assertNotIn('<!--',rendered)
            self.assertIn('addEventListener',rendered)
            build(page,1000)
            self.assertIn('Trufa Tradicional',page.read_text(encoding='utf-8'))
            self.assertIn('R$ 5,00',page.read_text(encoding='utf-8'))

    def test_form_reply_uses_documented_answer_object(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge=OpenCodeAgent(directory);bridge.api_version=2;bridge.session_id='session'
            requests=[];bridge._request=lambda *args,**kwargs:requests.append(args)
            bridge.respond_form('question',{'approval':'Executar'})
            self.assertEqual(requests[0],('POST','/api/session/session/form/question/reply',{'answer':{'approval':'Executar'}}))
            bridge.respond_form('question',None)
            self.assertEqual(requests[-1][:2],('DELETE','/api/session/session/form/question'))

    def test_form_wait_is_visible_and_not_execution_time(self):
        tick=[0.0];progress=ExecutionProgress(clock=lambda:tick[0])
        progress.observe({'type':'form.created','data':{'form':{'id':'f','sessionID':'s','title':'Escolha','fields':[]}}})
        tick[0]=100
        self.assertEqual(progress.snapshot()['phase'],'waiting_question')
        self.assertEqual(progress.snapshot()['waiting_seconds'],100)
        progress.observe({'type':'form.replied','data':{'id':'f'}})
        tick[0]=110
        self.assertEqual(progress.snapshot()['waiting_seconds'],100)
        self.assertNotEqual(progress.snapshot()['phase'],'waiting_question')

    def test_native_question_dialog_returns_selected_value(self):
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QComboBox,QDialogButtonBox
        from nexus.agent_forms import ask_form
        def respond():
            dialog=self.app.activeModalWidget()
            if not dialog:QTimer.singleShot(10,respond);return
            combo=dialog.findChild(QComboBox,'FormField_approval')
            combo.setCurrentIndex(1)
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
        QTimer.singleShot(20,respond)
        answer=ask_form(None,{'id':'f','title':'Escolha para teste','fields':[{'key':'approval','type':'string','required':True,'options':[{'value':'Executar','label':'Executar gerador'},{'value':'Não executar','label':'Não executar'}]}]})
        self.assertEqual(answer,{'approval':'Executar'})

class ServiceRepairTests(unittest.TestCase):
    def service(self,directory):
        self.answers=[];self.errors=[];self.events=[]
        service=AgentService(directory,lambda _:None,lambda *x:self.answers.append(x),self.errors.append,self.events.append,lambda _:None)
        self.addCleanup(service.shutdown);return service

    def test_wrong_count_is_retried_once_and_only_verified_result_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            page=Path(directory)/'alvo.html';page.write_text('<html>original</html>',encoding='utf-8')
            service=self.service(directory)
            class Bridge:
                session_id='test-repair';process=types.SimpleNamespace(poll=lambda:None)
                n=0;items=[]
                def messages(self):return self.items
                def status(self):return {'type':'idle'}
                def prompt(self,text,**kw):
                    self.n+=1
                    count=17 if self.n==1 else 1000
                    page.write_text('\n'.join(f'<p>Produto {i}</p>' for i in range(count)),encoding='utf-8')
                    self.items=self.items+[{'id':f'a{self.n}','type':'assistant','finish':'stop','time':{'completed':1},'content':[{'type':'text','text':'Arquivo ajustado.'}]}]
                def stop(self):pass
            bridge=Bridge();service.bridge=bridge
            with patch('nexus.agent_service.time.sleep',return_value=None):
                service._run('Altere o arquivo HTML para 1000 linhas','build',{'id':'gpt-6-sol'},'high','texto',False,target_file=page)
            self.assertEqual(bridge.n,2);self.assertFalse(self.errors)
            self.assertEqual(len(self.answers),1);self.assertIn('Verificação local:',self.answers[0][0])
            self.assertEqual(len(page.read_text(encoding='utf-8').splitlines()),1000)

    def test_no_progress_is_cancelled_and_not_called_successful(self):
        with tempfile.TemporaryDirectory() as directory:
            service=self.service(directory);tick=[0.0];service.progress=ExecutionProgress(clock=lambda:tick[0])
            class Bridge:
                session_id='test-stall';process=types.SimpleNamespace(poll=lambda:None);stopped=False
                def messages(self):return []
                def prompt(self,*a,**kw):pass
                def status(self):return {'type':'idle' if self.stopped else 'busy'}
                def interrupt_and_wait(self,timeout):self.stopped=True;return True
                def stop(self):pass
            bridge=Bridge();service.bridge=bridge
            with patch('nexus.agent_service.time.sleep',side_effect=lambda _:tick.__setitem__(0,tick[0]+130)):
                service._run('Edite o arquivo','build',{'id':'gpt-6-sol'},'high','texto',False)
            self.assertTrue(bridge.stopped);self.assertFalse(self.answers)
            self.assertIn('sem progresso confirmado',self.errors[0]);self.assertFalse(service.busy)

class VoiceFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_long_audio_uses_bounded_slices_instead_of_overflow(self):
        class Sink(PCMPlayer):
            def __init__(self):self.cancelled=lambda:False;self.chunks=[];self.waits=0
            @property
            def pending_seconds(self):
                self.waits+=1
                return 6 if self.waits==1 else 0
            def feed(self,data,rate):self.chunks.append(data)
        sink=Sink();audio=b'\0\1'*(24000*35)
        await sink.enqueue(audio,24000)
        self.assertEqual(b''.join(sink.chunks),audio);self.assertLessEqual(max(map(len,sink.chunks)),4800)

class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def window(self):
        from ui import MainWindow
        with patch.object(MainWindow,'_check_config',return_value=True):window=MainWindow('face.png')
        self.addCleanup(window.close);return window

    def test_execution_is_real_separate_tab_and_settings_are_modeless(self):
        window=self.window();window.resize(1280,760)
        window._open_agent_execution()
        self.assertEqual(window._center_tabs.tabText(1),'EXECUÇÃO DO AGENTE')
        self.assertIs(window._center_tabs.currentWidget(),window._agent_execution)
        panel=window._agent_execution
        panel.append({'ts':time.time(),'type':'session.tool.input.started','tool_id':'tool','tool':'patch','label':'Preparando patch'})
        panel.append({'ts':time.time(),'type':'nexus.tool.preparing','tool_id':'tool','tool':'patch','label':'Preparando patch','detail':'12000 caracteres recebidos'})
        self.assertEqual(panel.tree.topLevelItemCount(),1)
        self.assertIn('12000',panel.tree.topLevelItem(0).text(2))
        window._open_agent_dialog();self.assertFalse(window._agent_cockpit.isModal())
        self.assertLessEqual(window.minimumSizeHint().height(),900)

    def test_voice_vision_question_goes_through_preview_and_bytes(self):
        window=self.window();window._agent_enabled=True;calls=[]
        class Service:
            busy=False
            def submit(self,*a,**kw):calls.append((a,kw));return True
            def shutdown(self):pass
        window._agent_service=Service()
        with patch('nexus.agent_screen.approve_capture',return_value=b'approved-image') as preview:
            self.assertTrue(window._agent_submit_on_ui('Fala aí, tu consegue ver minha tela?','voz'))
        self.assertEqual(preview.call_count,1)
        self.assertEqual(calls[0][1]['image'],b'approved-image')

    def test_cancel_tool_failure_event_does_not_crash_ui(self):
        window=self.window()
        window._agent_event_on_ui({'type':'session.tool.failed','data':{'error':'Tool execution interrupted','sessionID':'synthetic'}})

if __name__=='__main__':unittest.main()
