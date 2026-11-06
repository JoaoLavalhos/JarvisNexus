"""NEXUS Agent: bridge to official OpenCode HTTP server.

Runs a *separate* local OpenCode process only when Agent mode is requested;
never changes the machine's OpenCode auth or executes tools itself.
API compatible with the documented OpenCode 1.x server endpoints.
"""
from __future__ import annotations

import atexit
import base64
import hashlib
import mimetypes
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from typing import Any
from nexus import diagnostics as diag
from nexus.agent_permissions import load_rules


class AgentError(RuntimeError):
    pass


class OpenCodeAgent:
    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace).expanduser().resolve(strict=True)
        if not self.workspace.is_dir():
            raise AgentError('Diretório de trabalho inválido.')
        self.process: subprocess.Popen | None = None
        self.base_url = ''
        self.password = secrets.token_urlsafe(36)
        self.session_id: str | None = None
        self.api_version = 1
        self._events_stop = threading.Event()
        self._event_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._log_cursor = None
        self._recovery_lock = threading.Lock()
        atexit.register(self.stop)

    @staticmethod
    def _port() -> int:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            return sock.getsockname()[1]

    def _request(self, method: str, path: str, body: Any = None, timeout: float = 7) -> Any:
        url = self.base_url + path
        encoded = None if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8')
        token = base64.b64encode(('opencode:' + self.password).encode()).decode()
        req = Request(url, data=encoded, method=method, headers={
            'Authorization': 'Basic ' + token,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        })
        try:
            with urlopen(req, timeout=timeout) as response:
                payload = response.read()
                if not payload:
                    return None
                return json.loads(payload)
        except HTTPError as exc:
            raw = exc.read(700).decode('utf-8', errors='replace')
            raise AgentError(f'OpenCode HTTP {exc.code}: {raw}') from exc
        except (OSError, ValueError, TimeoutError) as exc:
            raise AgentError(f'Comunicação com OpenCode: {exc}') from exc

    def start(self, on_event=None) -> dict:
        if self.process and self.process.poll() is None:
            return self.health()
        executable = shutil.which('opencode')
        if not executable:
            raise AgentError('O comando opencode não está no PATH do Windows. Rode "opencode --version" no terminal; reinstale o CLI oficial se não existir.')
        port = self._port()
        self.base_url = f'http://127.0.0.1:{port}'
        env = os.environ.copy()
        env['OPENCODE_SERVER_PASSWORD'] = self.password
        env['OPENCODE_SERVER_USERNAME'] = 'opencode'
        # Later config layer: require approval for edits and terminal commands,
        # and forbid access outside the explicitly chosen workspace.
        # OpenCode V2 expects an ORDERED permissions ruleset. Legacy
        # 'permission': {'bash': ...} is not reliably honored by V2.
        # Do not allow unreviewed writes or arbitrary terminal commands.
        env['OPENCODE_CONFIG_CONTENT'] = json.dumps({
            'permissions': load_rules(self.workspace)
        })
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        try:
            self.process = subprocess.Popen(
                [executable, 'serve', '--hostname', '127.0.0.1', '--port', str(port)],
                cwd=str(self.workspace), env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                creationflags=flags if os.name == 'nt' else 0,
            )
        except OSError as exc:
            raise AgentError(f'Não foi possível iniciar o CLI: {exc}') from exc
        def capture_stderr(proc):
            if proc.stderr:
                for line in iter(proc.stderr.readline,b''):
                    data=line.decode('utf-8','replace').strip()
                    if data:diag.warning('opencode.stderr',message=data[:400])
        threading.Thread(target=capture_stderr,args=(self.process,),daemon=True,name='OpenCodeStderr').start()
        deadline = time.monotonic() + 18
        last = ''
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise AgentError(f'O OpenCode encerrou com código {self.process.returncode}. Teste: opencode serve --hostname 127.0.0.1 --port 4096')
            try:
                health = self.health()
                if health.get('healthy'):
                    if on_event:
                        self.start_events(on_event)
                    return health
            except AgentError as exc:
                last = str(exc)
            time.sleep(.35)
        self.stop()
        raise AgentError('OpenCode não iniciou dentro do limite de espera. '+last)

    def health(self) -> dict:
        try:
            data = self._request('GET', '/global/health', timeout=2)
            self.api_version = 1
            if not isinstance(data,dict):raise AgentError('Resposta inesperada do servidor v1.')
            return data
        except AgentError as first:
            # OpenCode v2 has a new experimental /api surface.
            try:
                data=self._request('GET','/api/info',timeout=2)
                if not isinstance(data,dict):raise AgentError('Resposta inesperada do servidor v2.')
                self.api_version = 2
                body=data.get('data',data)
                return {'healthy':True,'version':str(body.get('version') or body.get('name') or 'v2')}
            except AgentError:
                raise first

    def get_config(self) -> dict:
        x = self._request('GET', '/config' if self.api_version==1 else '/api/config')
        return x if isinstance(x, dict) else {}

    def get_models(self) -> list[dict]:
        """Read model catalog from the right endpoint for each OpenCode version."""
        known=[]
        if self.api_version==2:
            response=self._request('GET','/api/model',timeout=15)
            values=response.get('data',[]) if isinstance(response,dict) else []
            if isinstance(values,dict):values=list(values.values())
            for m in values if isinstance(values,list) else []:
                if not isinstance(m,dict):continue
                pid=m.get('providerID') or m.get('providerId')
                mid=m.get('id') or m.get('modelID')
                if not pid or not mid:continue
                if pid=='openai' or 'gpt' in str(m.get('name','')).lower():
                    vs=m.get('variants',[])
                    vs=(list(vs) if isinstance(vs,dict) else
                        [v if isinstance(v,str) else v.get('id') for v in vs
                         if isinstance(v,str) or isinstance(v,dict)] if isinstance(vs,list) else [])
                    known.append({'name':m.get('name',mid),'id':mid,'providerID':pid,'variants':vs,'capabilities':m.get('capabilities',{})})
        else:
            response=self.get_providers()
            for p in response.get('all',[]) if isinstance(response,dict) else []:
                pid=p.get('id','')
                ms=p.get('models',{})
                for mid,m in (ms.items() if isinstance(ms,dict) else []):
                    if pid=='openai' or 'gpt' in mid.lower():
                        known.append({'name':m.get('name',mid) if isinstance(m,dict) else mid,
                                      'id':mid,'providerID':pid,'variants':[]})
        return sorted(known,key=lambda m:str(m['name']).lower())

    def default_model(self):
        if self.api_version!=2:return None
        value=self._request('GET','/api/model/default',timeout=8)
        return value.get('data') if isinstance(value,dict) else None

    def get_providers(self) -> dict:
        x = self._request('GET', '/provider' if self.api_version==1 else '/api/provider', timeout=15)
        if self.api_version==2 and isinstance(x,dict):
            return {'all': x.get('data', [])}
        return x if isinstance(x, dict) else {}

    def new_session(self, title='NEXUS Agent'): 
        value = self._request('POST','/session' if self.api_version==1 else '/api/session',{'title':title})
        if self.api_version==2 and isinstance(value,dict):value=value.get('data',value)
        if not isinstance(value,dict) or not value.get('id'):
            raise AgentError('OpenCode não retornou o ID da nova sessão.')
        self.session_id = value['id']
        self._log_cursor = None
        return self.session_id

    def prompt(self, text: str, agent='plan', model=None, variant=None, image=None) -> None:
        if not self.session_id:
            raise AgentError('Crie uma sessão antes de enviar tarefas.')
        body: dict = {'agent':agent,'parts':[{'type':'text','text':text}]}
        if model:
            body['model'] = {'providerID':model.get('providerID'),'modelID':model.get('id') or model.get('modelID')}
        if variant:
            body['variant'] = variant
        sid=quote(self.session_id)
        files=[]
        if image is not None:
            if not isinstance(image, (bytes, bytearray)) or len(image)>3_000_000:
                raise AgentError('Captura de tela inválida ou acima de 3 MB.')
            if model and isinstance(model.get('capabilities',{}).get('input'),list) and 'image' not in model['capabilities']['input']:
                raise AgentError('O modelo selecionado não aceita imagens. Escolha um modelo com visão.')
            # OpenCode V2 PromptInput.FileAttachment accepts a data URI.
            files=[{'uri': 'data:image/jpeg;base64,' + base64.b64encode(image).decode('ascii'),
                    'name': 'captura_tela_nexus.jpg', 'source': {'type':'inline'}}]
        if self.api_version==2:
            self._request('POST',f'/api/session/{sid}/agent',{'agent':agent})
            if model:
                ref={'id':model.get('id') or model.get('modelID'),
                     'providerID':model.get('providerID')}
                if variant:ref['variant']=variant
                self._request('POST',f'/api/session/{sid}/model',{'model':ref})
            payload={'text':text}
            if files:payload['files']=files
            self._request('POST',f'/api/session/{sid}/prompt',payload,timeout=25)
        else:
            if image is not None:
                body['parts'].append({'type':'file','mime':'image/jpeg',
                  'url':files[0]['uri'],'filename':'captura_tela_nexus.jpg'})
            self._request('POST',f'/session/{sid}/prompt_async',body,timeout=25)

    def verify_image_attachment(self, image, previous_user_ids=(), timeout=6, cancelled=lambda:False):
        """Confirm the exact bytes on a NEW projected user message, not just HTTP 200."""
        expected=hashlib.sha256(image).digest();deadline=time.monotonic()+timeout
        previous=set(previous_user_ids)
        while time.monotonic()<deadline and not cancelled():
            for msg in reversed(self.messages()):
                info=msg.get('info',msg)
                if (info.get('role') or info.get('type'))!='user':continue
                if str(info.get('id') or '') in previous:continue
                attachments=list(info.get('files') or msg.get('files') or [])
                attachments.extend(part for part in msg.get('parts',[]) if part.get('type')=='file')
                for file in attachments:
                    encoded=file.get('data') or file.get('uri') or file.get('url') or ''
                    if not isinstance(encoded,str):continue
                    if encoded.startswith('data:'):
                        header,_,encoded=encoded.partition(',')
                        if ';base64' not in header:continue
                    try:binary=base64.b64decode(encoded,validate=True)
                    except (ValueError,TypeError):continue
                    if hashlib.sha256(binary).digest()==expected:
                        return {'message_id':info.get('id'),'bytes':len(binary),'sha256':hashlib.sha256(binary).hexdigest()}
            time.sleep(.15)
        raise AgentError('A captura não foi confirmada no pedido recebido pelo OpenCode. Nenhuma análise de tela será declarada concluída; tente novamente pelo botão de captura.')

    def status(self) -> dict:
        if self.api_version==2:
            statuses=self._request('GET','/api/session/active',timeout=3)
            if not isinstance(statuses,dict):return {'type':'unknown'}
            busy=statuses.get('data',{})
            if isinstance(busy,dict):active=self.session_id in busy
            elif isinstance(busy,list):active=any((x.get('id') or x.get('sessionID'))==self.session_id for x in busy if isinstance(x,dict))
            else:return {'type':'unknown'}
            return {'type':'busy' if active else 'idle'}
        statuses = self._request('GET','/session/status',timeout=3)
        if not isinstance(statuses,dict): return {}
        return statuses.get(self.session_id or '',{}) or {}

    def messages(self) -> list:
        if not self.session_id: return []
        path=(f'/session/{quote(self.session_id)}/message?limit=80' if self.api_version==1
              else f'/api/session/{quote(self.session_id)}/message?limit=80&order=desc')
        v=self._request('GET',path,timeout=8)
        if self.api_version==2 and isinstance(v,dict):v=list(reversed(v.get('data',[])))
        return v if isinstance(v,list) else []

    def abort(self) -> None:
        if self.session_id:
            path=(f'/session/{quote(self.session_id)}/abort' if self.api_version==1
                  else f'/api/session/{quote(self.session_id)}/interrupt')
            self._request('POST',path,{},timeout=5)

    def pending_permissions(self):
        if self.api_version!=2 or not self.session_id:return []
        response=self._request('GET',f'/api/session/{quote(self.session_id)}/permission',timeout=5)
        return response.get('data',[]) if isinstance(response,dict) else []

    def pending_forms(self):
        if self.api_version!=2 or not self.session_id:return []
        response=self._request('GET',f'/api/session/{quote(self.session_id)}/form',timeout=5)
        return response.get('data',[]) if isinstance(response,dict) else []

    def respond_form(self,form_id,answer):
        path=f'/api/session/{quote(self.session_id)}/form/{quote(form_id)}'
        if answer is None:return self._request('DELETE',path,timeout=7)
        return self._request('POST',path+'/reply',{'answer':answer},timeout=7)

    def respond_permission(self, permission_id: str, approve: bool) -> None:
        if self.session_id and permission_id:
            if self.api_version==2:
                self._request('POST',f'/api/session/{quote(self.session_id)}/permission/{quote(permission_id)}/reply',
                              {'decision':'once' if approve else 'reject'}, timeout=7)
            else:
                self._request('POST',f'/session/{quote(self.session_id)}/permissions/{quote(permission_id)}',
                              {'response':'once' if approve else 'reject','remember': False},timeout=7)

    def diff(self):
        if self.api_version!=2 or not self.session_id:return []
        value=self._request('GET',f'/api/session/{quote(self.session_id)}/diff?context=3',timeout=10)
        return value.get('data',[]) if isinstance(value,dict) else []

    def interrupt_and_wait(self, timeout=8):
        self.abort()
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if self.process and self.process.poll() is not None:return True
            try:
                if self.status().get('type')=='idle':return True
            except AgentError:pass
            time.sleep(.2)
        return False

    @staticmethod
    def _decode_sse(lines):
        pieces=[]; ident=None; event=''
        for raw in lines:
            line=raw.decode('utf-8',errors='replace').rstrip('\r\n')
            if line.startswith('id:'):ident=line[3:].strip()
            elif line.startswith('event:'):event=line[6:].strip()
            elif line.startswith('data:'):pieces.append(line[5:].lstrip())
            elif not line and pieces:
                item=json.loads('\n'.join(pieces))
                if isinstance(item,str):item=json.loads(item)
                yield ident,event,item
                pieces=[];ident=None;event=''

    def recover_events(self, callback):
        if self.api_version!=2 or not self.session_id:return False
        if not self._recovery_lock.acquire(blocking=False):return False
        try:
            path=f'/api/experimental/session/{quote(self.session_id)}/log?follow=false'
            if self._log_cursor:path+='&after='+quote(self._log_cursor,safe='')
            token=base64.b64encode(('opencode:'+self.password).encode()).decode()
            request=Request(self.base_url+path,headers={'Authorization':'Basic '+token,'Accept':'text/event-stream'})
            count=0
            with urlopen(request,timeout=8) as response:
                for ident,event,item in self._decode_sse(response):
                    if self._events_stop.is_set():return False
                    if isinstance(item,dict) and item.get('type')=='log.synced':
                        if ident:self._log_cursor=ident
                        break
                    if isinstance(item,dict):callback(item);count+=1
                    if ident:self._log_cursor=ident
                    if count>10000:raise AgentError('Histórico muito extenso; recuperação parcial.')
            pending=self._request('GET',f'/api/session/{quote(self.session_id)}/permission',timeout=5)
            for item in pending.get('data',[]) if isinstance(pending,dict) else []:
                callback({'type':'permission.asked','properties':item})
            for form in self.pending_forms():callback({'type':'form.created','properties':{'form':form}})
            callback({'type':'nexus.stream.recovered','properties':{'sessionID':self.session_id,'message':f'{count} eventos reconciliados'}})
            return True
        except Exception as exc:
            diag.warning('opencode.events.recovery_failed',reason=type(exc).__name__)
            callback({'type':'nexus.stream.gap','properties':{'sessionID':self.session_id,'message':'Sem recuperação completa; conclusão exige mensagem final ou evento confirmado.'}})
            return False
        finally:self._recovery_lock.release()

    def start_events(self, callback):
        self._events_stop.clear()
        def runner():
            connected_before=False
            while not self._events_stop.is_set() and self.process and self.process.poll() is None:
                try:
                    token=base64.b64encode(('opencode:'+self.password).encode()).decode()
                    request=Request(self.base_url+('/event' if self.api_version==1 else '/api/event'),
                        headers={'Authorization':'Basic '+token,'Accept':'text/event-stream'})
                    with urlopen(request,timeout=45) as response:
                        callback({'type':'nexus.stream.connected','properties':{'sessionID':self.session_id or ''}})
                        if connected_before:self.recover_events(callback)
                        connected_before=True
                        for ident,event,item in self._decode_sse(response):
                            if self._events_stop.is_set():return
                            if isinstance(item,dict):callback(item)
                except Exception as exc:
                    if not self._events_stop.is_set():
                        callback({'type':'nexus.stream.disconnected','properties':{'sessionID':self.session_id or '',
                            'message':type(exc).__name__}})
                    if self._events_stop.wait(.8):return
        self._event_thread=threading.Thread(target=runner,name='OpenCode-SSE',daemon=True)
        self._event_thread.start()

    def stop(self):
        """Only the process tree launched by this bridge; wait after terminate/kill."""
        with self._lock:
            self._events_stop.set()
            process=self.process
            if not process:return True
            import psutil
            children=[]
            try:
                parent=psutil.Process(process.pid)
                children=parent.children(recursive=True)
            except psutil.NoSuchProcess:parent=None
            targets=children+([parent] if parent else [])
            for child in reversed(targets):
                try:child.terminate()
                except psutil.NoSuchProcess:pass
            _,alive=psutil.wait_procs(targets,timeout=3)
            for child in alive:
                try:child.kill()
                except psutil.NoSuchProcess:pass
            _,alive=psutil.wait_procs(alive,timeout=3)
            if alive:raise AgentError('Não foi possível confirmar o encerramento de processos do agente.')
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:raise AgentError('Processo do agente ainda está ativo.')
            self.process=None
            return True
