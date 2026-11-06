"""V18 regressions: terminal lifecycle, independent Live voice, capture consent."""
from __future__ import annotations
import ast
import asyncio
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from google import genai
from nexus.task_state import TaskState,Phase
from nexus.agent_activity import ActivityLedger,normalize_event
from nexus.agent_service import AgentService
from nexus.agent_voice import AgentVoice,transcript_matches,quota_cooldown
from nexus.opencode_agent import OpenCodeAgent,AgentError
from nexus.agent_permissions import validate_rules
from nexus import agent_screen

ROOT=Path(__file__).resolve().parents[1]


class Process:
    def poll(self):return None


class Bridge:
    def __init__(self,callback=lambda _:None,final=True,stop_fails=False):
        self.process=Process();self.session_id='v18';self.api_version=2
        self.callback=callback;self.final=final;self.stop_fails=stop_fails
        self.items=[];self.sent=[];self.aborted=0
    def messages(self):return self.items
    def status(self):return {'type':'busy' if self.stop_fails else 'idle'}
    def prompt(self,text,**kwargs):
        self.sent.append((text,kwargs))
        info={'role':'assistant','id':'new'}
        if self.final:info.update(finish='stop',time={'completed':1})
        self.items=[{'info':info,'parts':[{'type':'text','text':'Resposta final.'}]}]
    def interrupt_and_wait(self,timeout):self.aborted+=1;return not self.stop_fails
    def stop(self):
        if self.stop_fails:raise AgentError('encerramento não confirmado')
        self.process=None


class ServiceTests(unittest.TestCase):
    def service(self):
        self.answers=[];self.errors=[];self.events=[]
        service=AgentService(tempfile.gettempdir(),lambda _:None,lambda *x:self.answers.append(x),self.errors.append,self.events.append,lambda _:None)
        self.addCleanup(service.shutdown)
        return service

    def run_service(self,service,**kw):
        with patch('nexus.agent_service.time.sleep',return_value=None):
            service._run('Tarefa de teste','plan',{'id':'gpt-6-sol','providerID':'openai'},'high','texto',False,**kw)

    def test_final_answer_with_completed_metadata(self):
        service=self.service();service.bridge=Bridge()
        self.run_service(service)
        self.assertFalse(self.errors);self.assertEqual(self.answers[0][0],'Resposta final.')
        self.assertEqual(service.task_state.snapshot()['phase'],'succeeded')
        self.assertIn('modelo=gpt-6-sol',service.bridge.sent[0][0])
        self.assertFalse(service.busy)

    def test_preamble_without_terminal_proof_is_failure(self):
        service=self.service();service.bridge=Bridge(final=False)
        self.run_service(service)
        self.assertFalse(self.answers);self.assertIn('sem confirmação',self.errors[0])
        self.assertEqual(service.task_state.snapshot()['phase'],'failed')

    def test_timeout_does_not_free_unconfirmed_execution(self):
        service=self.service();service.bridge=Bridge(stop_fails=True);service._max_runtime_sec=0
        self.run_service(service)
        self.assertFalse(self.answers)
        self.assertTrue(service._quarantined)
        self.assertFalse(service.submit('Outra tarefa'))
        self.assertEqual(service.task_state.snapshot()['phase'],'recovery_required')
        self.assertGreaterEqual(service.bridge.aborted,1)
        # Avoid noisy asynchronous shutdown of this deliberately unkillable fake.
        service.bridge=None

    def test_cancel_before_prompt_prevents_submission(self):
        service=self.service();bridge=Bridge();service.bridge=bridge
        service._busy=True;service.cancel();self.run_service(service)
        self.assertFalse(bridge.sent)
        self.assertFalse(service.busy)
        self.assertEqual(service.task_state.snapshot()['phase'],'cancelled')

    def test_capture_cannot_be_requested_without_approved_bytes(self):
        service=self.service()
        self.assertFalse(service.submit('Veja a tela',include_screen=True))
        self.assertFalse(service.busy)

    def test_exact_approved_image_forwarded(self):
        service=self.service();service.bridge=Bridge()
        image=b'approved synthetic bytes'
        self.run_service(service,include_screen=True,image=image)
        self.assertIs(service.bridge.sent[0][1]['image'],image)


class LedgerTests(unittest.TestCase):
    def test_real_v2_tool_content_duration_and_dedup(self):
        ledger=ActivityLedger();ledger.begin('s')
        ledger.receive({'id':'e1','type':'session.tool.input.started','data':{'sessionID':'s','id':'call','name':'shell'}})
        ledger.receive({'id':'e2','type':'session.tool.called','data':{'sessionID':'s','id':'call','input':{'command':'python check.py'}}})
        raw={'id':'e3','type':'session.tool.success','data':{'sessionID':'s','id':'call','content':[{'type':'text','text':'OK 18'}]}}
        item=ledger.receive(raw)
        self.assertEqual(item['tool'],'shell');self.assertIn('OK 18',item['output'])
        self.assertIsNotNone(item['duration']);self.assertIsNone(ledger.receive(raw))
        ledger.receive({'type':'session.step.ended','data':{'sessionID':'s'}})
        self.assertFalse(ledger.summary()['completed'])

    def test_stale_execution_success_cannot_complete_new_turn(self):
        ledger=ActivityLedger();ledger.begin('s')
        self.assertIsNone(ledger.receive({'id':'old','created':(time.time()-10)*1000,'type':'session.execution.succeeded','data':{'sessionID':'s'}}))
        self.assertFalse(ledger.summary()['completed'])

    def test_structured_secrets_redacted(self):
        item=normalize_event({'type':'session.tool.called','data':{'input':{'api_key':'SECRET_EXAMPLE_VALUE','token':'PRIVATE_TEST_VALUE','command':'test'}}})
        self.assertNotIn('SECRET_EXAMPLE_VALUE',item['arguments'])
        self.assertNotIn('PRIVATE_TEST_VALUE',item['detail'])

    def test_crash_state_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json';state=TaskState(path)
            run=state.begin({'id':'gpt-6-sol'})
            recovered=TaskState(path).snapshot()
            self.assertEqual(recovered['id'],run['id'])
            self.assertEqual(recovered['phase'],'recovery_required')
            state.set(Phase.SUCCEEDED)
            self.assertEqual(TaskState(path).snapshot()['phase'],'succeeded')

    def test_permission_rules_reject_blanket_shell_allow(self):
        with self.assertRaises(ValueError):validate_rules([{'action':'shell','resource':'*','effect':'allow'}])
        self.assertEqual(validate_rules([{'action':'shell','resource':'python validar.py','effect':'ask'}])[0]['effect'],'ask')


class VoiceTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    async def test_live_relay_has_no_tools_and_does_not_use_tts(self):
        sent=[];configurations=[];played=[]
        content=types.SimpleNamespace(output_transcription=types.SimpleNamespace(text='Teste Jarvis.'),interrupted=False,
            model_turn=types.SimpleNamespace(parts=[types.SimpleNamespace(inline_data=types.SimpleNamespace(data=b'\0'*120,mime_type='audio/pcm;rate=24000'))]),turn_complete=True)
        class Session:
            async def send_client_content(self,**kw):sent.append(kw)
            async def receive(self):yield types.SimpleNamespace(server_content=content)
        class Manager:
            async def __aenter__(self):return Session()
            async def __aexit__(self,*_):pass
        class Client:
            def __init__(self,**kw):self.aio=types.SimpleNamespace(live=self,aclose=self.close)
            def connect(self,**kw):configurations.append(kw);return Manager()
            async def close(self):pass
        class Sink:
            def __init__(self,cancelled,started):self.started=started
            def feed(self,data,rate):played.append((data,rate));self.started()
            async def drain(self):pass
            def close(self):pass
        voice=AgentVoice();phases=[];voice._emit=lambda generation,phase,text:phases.append(phase)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'config').mkdir()
            (root/'config'/'api_keys.json').write_text(json.dumps({'gemini_api_key':'synthetic-test-key'}),encoding='utf-8')
            with patch.object(genai,'Client',Client),patch('nexus.agent_voice.PCMPlayer',Sink),patch('nexus.agent_voice.ROOT',root):
                await voice._relay('Teste Jarvis.','Charon',voice._generation)
        self.assertEqual(played[0][1],24000)
        config=configurations[0]['config']
        self.assertNotIn('tools',config)
        self.assertEqual(config['speech_config']['voice_config']['prebuilt_voice_config']['voice_name'],'Charon')
        self.assertEqual(json.loads(sent[0]['turns']['parts'][0]['text'])['texto_para_ler'],'Teste Jarvis.')
        self.assertIn('verified',phases)

    async def test_cancel_generation_discards_late_audio(self):
        voice=AgentVoice();events=[];voice.status_changed.connect(events.append)
        stale=voice._generation;voice.stop();voice._emit(stale,'failed','stale failure')
        self.app.processEvents()
        self.assertFalse(events)

    async def test_ptt_stop_does_not_gate_first_word_when_idle(self):
        voice=AgentVoice()
        voice.stop()
        self.assertFalse(voice.speaking)
        voice._active=True  # connecting is not audible playback
        self.assertFalse(voice.speaking)
        voice._playing=True
        voice.stop(clear_tail=True)
        self.assertFalse(voice.speaking)
        self.assertEqual(voice._tail_until,0.0)

    async def test_quota_retry_and_transcript_fidelity(self):
        self.assertEqual(quota_cooldown(Exception('429 retryDelay: "120s"')),120)
        self.assertEqual(quota_cooldown(Exception('bad device')),0)
        self.assertTrue(transcript_matches('Olá, senhor!','Olá senhor.'))
        self.assertFalse(transcript_matches('Exclua somente o temporário.','Exclua o projeto.'))


class CaptureAndRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_preview_approves_exact_image_and_monitor(self):
        from PIL import Image
        out=io.BytesIO();Image.new('RGB',(40,40),'blue').save(out,format='JPEG');image=out.getvalue()
        def approve():
            dialog=self.app.activeModalWidget()
            if dialog is None:QTimer.singleShot(10,approve);return
            dialog.monitor.setCurrentIndex(1)
            dialog.send.click()
        with patch.object(agent_screen,'monitors',return_value=[{'width':40,'height':40,'left':0,'top':0},{'width':40,'height':40,'left':40,'top':0}]),patch.object(agent_screen,'capture_jpeg',return_value=image) as capture:
            QTimer.singleShot(20,approve)
            result=agent_screen.approve_capture(None)
        self.assertEqual(result,image)
        self.assertEqual(capture.call_args.args[0],2)

    def test_rejected_preview_never_returns_image(self):
        from PIL import Image
        out=io.BytesIO();Image.new('RGB',(40,40)).save(out,format='JPEG')
        QTimer.singleShot(20,lambda:self.app.activeModalWidget().reject())
        with patch.object(agent_screen,'monitors',return_value=[{'width':40,'height':40,'left':0,'top':0}]),patch.object(agent_screen,'capture_jpeg',return_value=out.getvalue()):
            self.assertIsNone(agent_screen.approve_capture(None))

    def test_groq_source_kept_byte_for_byte(self):
        manifest=json.loads((ROOT/'BASELINE-V17.json').read_text(encoding='utf-8'))
        # Manifest format is intentionally explicit in the release artifact.
        original={k.replace('\\','/'):v for k,v in manifest.get('files',manifest).items()}
        value=original['core/groq_stt.py']
        if isinstance(value,dict):value=value.get('sha256')
        self.assertEqual(hashlib.sha256((ROOT/'core'/'groq_stt.py').read_bytes()).hexdigest(),value)

    def test_agent_microphone_loop_never_opens_live(self):
        tree=ast.parse((ROOT/'main.py').read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='JarvisLive')
        method=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_run_agent_microphone')
        namespace={'asyncio':asyncio};exec(compile(ast.Module(body=[method],type_ignores=[]),'route-test','exec'),namespace)
        ui=types.SimpleNamespace(agent_mode=True,set_state=lambda _:None,write_log=lambda _:None)
        async def microphone():
            await asyncio.sleep(.01);ui.agent_mode=False
        async def sleep_watch():await asyncio.Future()
        dummy=types.SimpleNamespace(ui=ui,_wake_enabled=False,_reconnect_event=asyncio.Event(),_listen_audio=microphone,_run_sleep_watch=sleep_watch,
            _speaking_lock=threading.Lock(),_is_speaking=True,_tail_until=time.monotonic()+100,_echo=types.SimpleNamespace(reset=lambda:None))
        asyncio.run(namespace['_run_agent_microphone'](dummy))
        self.assertIsNone(dummy.session)
        self.assertIsNone(dummy._engine)
        self.assertFalse(dummy._is_speaking)
        self.assertEqual(dummy._tail_until,0.0)

    def test_voice_failure_releases_hud_without_changing_task(self):
        from ui import MainWindow
        window=MainWindow('face.png')
        try:
            window._agent_enabled=True
            window._agent_service=types.SimpleNamespace(busy=False,shutdown=lambda:None)
            window._state_sig.emit('THINKING')
            generation=window._agent_voice._generation
            window._agent_voice._active=True
            window._agent_voice._deliver(generation,'failed','Quota da voz atingida.')
            self.app.processEvents()
            self.assertEqual(window.hud.state,'LISTENING')
            self.assertFalse(window._agent_voice._active)
            window._agent_service.busy=True
            window._agent_voice._deliver(generation,'failed','Outro erro da voz.')
            self.app.processEvents()
            self.assertEqual(window.hud.state,'THINKING')
        finally:window.close()

    def test_native_input_uses_hardware_rate(self):
        from core import audio_devices
        import sounddevice as sd
        with patch.object(sd,'query_devices',return_value={'default_samplerate':48000}):
            audio_devices.configure(16000,24000,native_input=True)
            self.assertEqual(audio_devices.stream_rate(3,'input'),48000)
            self.assertEqual(audio_devices.stream_rate(3,'output'),24000)
        audio_devices.configure(16000,24000)

    def test_switch_to_gpt_cancels_pending_gemini_handshake(self):
        tree=ast.parse((ROOT/'main.py').read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='JarvisLive')
        method=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_open_session')
        class Reconnect(Exception):
            def __init__(self,**kw):pass
        closed=[];cancelled=[]
        class Manager:
            async def __aenter__(self):
                try:await asyncio.Future()
                finally:cancelled.append(True)
            async def __aexit__(self,*_):pass
        class Client:
            def __init__(self,**kw):self.aio=types.SimpleNamespace(live=self,aclose=self.close)
            def connect(self,**kw):return Manager()
            async def close(self):closed.append(True)
        namespace={'asyncio':asyncio,'asynccontextmanager':contextlib.asynccontextmanager,
            'genai':types.SimpleNamespace(Client=Client),'_get_api_key':lambda:'synthetic', '_ReconnectSignal':Reconnect}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'connect-test','exec'),namespace)
        ui=types.SimpleNamespace(agent_mode=False)
        dummy=types.SimpleNamespace(_engine_caps=None,_enhanced_live=False,ui=ui)
        async def run():
            async def switch():await asyncio.sleep(.01);ui.agent_mode=True
            task=asyncio.create_task(switch())
            with self.assertRaises(Reconnect):
                async with namespace['_open_session'](dummy,'model',{}):self.fail('Live should not open')
            await task
        asyncio.run(run())
        self.assertTrue(closed);self.assertTrue(cancelled)

    def test_sse_encoded_durable_events(self):
        event={'type':'session.execution.succeeded','data':{'sessionID':'s'}}
        body=[b'id: 123\n',b'event: event\n',('data: '+json.dumps(json.dumps(event))+'\n').encode(),b'\n']
        parsed=list(OpenCodeAgent._decode_sse(body))
        self.assertEqual(parsed[0][0],'123');self.assertEqual(parsed[0][2],event)


if __name__=='__main__':unittest.main()
