"""Structured, privacy-conscious activity ledger for OpenCode sessions.

Treat an emitted step as progress, NEVER as proof of task success.
Only execution.succeeded + a final answer can mark a task successful.
"""
from __future__ import annotations
import json
import threading
import time
from pathlib import Path
from nexus import diagnostics as diag

ROOT=Path(__file__).resolve().parent.parent
LOG=diag.LOGS/'agent_activity.jsonl'

_TRANSLATIONS={
 'form.created': 'Agente aguarda sua resposta',
 'form.replied': 'Resposta enviada ao agente',
 'form.cancelled': 'Pergunta cancelada',
 'nexus.tool.preparing': 'Preparando ferramenta',
 'nexus.screen.attached': 'Captura recebida pelo agente',
 'nexus.verification': 'Verificação local dos arquivos',
 'nexus.commentary': 'Mensagem parcial · execução em andamento',
 'nexus.diff': 'Alterações de arquivos',
 'nexus.stream.connected': 'Eventos conectados',
 'nexus.stream.disconnected': 'Eventos desconectados; reconciliando',
 'nexus.stream.recovered': 'Histórico de eventos recuperado',
 'nexus.stream.gap': 'Histórico indisponível; estado consultado separadamente',
 'session.execution.started': 'Execução iniciada',
 'session.execution.succeeded': 'Execução concluída',
 'session.execution.failed': 'Execução falhou',
 'session.execution.interrupted': 'Execução interrompida',
 'session.step.started': 'Etapa iniciada',
 'session.step.ended': 'Etapa finalizada',
 'session.step.failed': 'Etapa falhou',
 'session.tool.input.started': 'Preparando ferramenta',
 'session.tool.input.ended': 'Argumentos recebidos',
 'session.tool.called': 'Ferramenta iniciada',
 'session.tool.progress': 'Ferramenta executando',
 'session.text.started': 'Gerando resposta',
 'session.text.ended': 'Resposta gerada',
 'session.reasoning.started': 'Raciocinando',
 'session.reasoning.ended': 'Raciocínio finalizado',
 'session.tool.success': 'Ferramenta concluída',
 'session.tool.failed': 'Ferramenta falhou',
 'permission.asked': 'Aguardando permissão',
 'permission.rejected': 'Permissão negada',
 'permission.replied': 'Permissão respondida',
 'session.idle':'Sessão aguardando',
 'session.status':'Estado atualizado',
 'session.retry.scheduled':'Nova tentativa agendada',
 'session.compaction.started':'Compactando contexto',
 'session.compaction.ended':'Contexto compactado',
}
BLOCKED={'permission.rejected'}
ERRORS={'session.execution.failed','session.tool.failed','session.step.failed','permission.rejected','session.error'}
SUCCESS={'session.execution.succeeded'}
INTERRUPTED={'session.execution.interrupted'}


def normalize_event(raw:dict)->dict|None:
    if not isinstance(raw,dict):return None
    # OpenCode emits {type,properties}, v2 streams can use {event,data}.
    et=raw.get('type') or raw.get('event') or ''
    data=raw.get('properties') or raw.get('data') or {}
    if isinstance(data,dict) and isinstance(data.get('data'),dict) and not data.get('sessionID'):
        # v2 envelope with nested event, but don't unnest actual payloads accidentally
        if data.get('type') or data.get('event'):
            et=data.get('type') or data.get('event')
            data=data.get('data')
    if not isinstance(data,dict):data={'message':str(data)}
    if et.startswith('form.') and isinstance(data.get('form'),dict):data=data['form']
    if et.startswith('session.') and et not in _TRANSLATIONS and et not in ('session.error',):
        return None
    if et in ('session.text.delta','session.reasoning.delta','session.step.streamed','session.tool.input.delta'):
        return None
    if et not in _TRANSLATIONS and et not in ERRORS and et not in ('permission.replied','permission.rejected'):return None
    session=data.get('sessionID') or data.get('sessionId')
    if not session and isinstance(data.get('session'),dict):session=data['session'].get('id')
    state=data.get('state') if isinstance(data.get('state'),dict) else {}
    part=data.get('part') if isinstance(data.get('part'),dict) else {}
    if not part and isinstance(data.get('message'),dict):
        part=data['message'].get('part',{}) if isinstance(data['message'].get('part'),dict) else {}
    if not state and isinstance(data.get('toolCall'),dict):
        state=data.get('toolCall')
    tool=(data.get('tool') or data.get('toolName') or data.get('name')
          or part.get('tool') or part.get('name') or state.get('tool') or state.get('name'))
    if isinstance(tool,dict):tool=tool.get('name') or tool.get('id')
    tool=tool or state.get('tool') or state.get('name') or ''
    error=data.get('error') or state.get('error') or data.get('reason') or data.get('message') or ''
    if isinstance(error,dict):error=error.get('message') or error.get('name') or str(error)
    params=(data.get('input') or data.get('args') or data.get('command') or data.get('path')
            or data.get('title') or part.get('input') or state.get('input')
            or state.get('args') or state.get('command') or '')
    if isinstance(params,(dict,list)):params=json.dumps(params,ensure_ascii=False)
    # For successful tools, surface output excerpts; complete payloads are not logged.
    if et in ('session.tool.success','session.tool.failed'):
        output = data.get('output') or state.get('output') or part.get('output')
        if output is not None:
            params = str(output)[:1500] or params
    blocked=(et in BLOCKED or 'external_directory' in str(error).lower() or
             'permission denied' in str(error).lower() or 'permission.rejected' in str(error).lower())
    if blocked and 'external_directory' in str(error):
        error=('Acesso a pasta fora do projeto foi bloqueado. Escolha o projeto correto em '
               'NEXUS Agent → Pasta de trabalho, ou aprove explicitamente uma solicitação de acesso.')
    metadata=data.get('metadata') or state.get('metadata') or {}
    exit_code=next((metadata[k] for k in ('exit','exitCode','exit_code') if k in metadata),None) if isinstance(metadata,dict) else None
    process_failed=et=='session.tool.success' and isinstance(exit_code,(int,float)) and exit_code!=0
    label=(f'Comando terminou com código {exit_code}' if process_failed else _TRANSLATIONS.get(et,et))
    if tool:label+=' · '+str(tool)[:90]
    output=data.get('output') or state.get('output') or data.get('content') or ''
    if isinstance(output,(dict,list)):output=json.dumps(output,ensure_ascii=False,indent=2)
    arguments=diag.sanitize(params)[:32000]
    output=diag.sanitize(output)[:64000]
    diff=diag.sanitize(json.dumps(data.get('diff'),ensure_ascii=False,indent=2))[:128000] if data.get('diff') else ''
    detail=str(error or params or output or diff or '')[:64000]
    if et=='permission.asked':detail=str(data.get('resources') or data.get('patterns') or data.get('permission') or detail)[:600]
    return {'ts':round((float(raw.get('created'))/(1000 if float(raw.get('created'))>1e11 else 1)) if isinstance(raw.get('created'),(float,int)) else time.time(),3),'type':str(et),'session':str(session or ''),
            'tool_id':str(data.get('id') or ''),'tool':str(tool or ''),
            'label':diag.sanitize(label),'detail':diag.sanitize(detail),
            'arguments':arguments,'output':output,'diff':diff,'duration':None,
            'event_id':str(raw.get('id') or ''),
            'exit_code':exit_code,'failure':et in ERRORS or blocked or process_failed,'blocked':blocked,'success':et in SUCCESS,
            'interrupted':et in INTERRUPTED}

class ActivityLedger:
    def __init__(self):
        self.lock=threading.Lock()
        self.events=[]
        self._task_start=0
        self._session=''
        self._status='AGUARDANDO'
        self._tool_names={}
        self._seen=set()
        self._tool_started={}
        self._wall_start=0
        self._attempt_index=0
    def begin(self,session:str,preserve=False):
        with self.lock:
            self._task_start=time.monotonic();self._wall_start=time.time();self._session=str(session)
            if not preserve:self.events=[]
            self._attempt_index=len(self.events)
            self._status='EXECUTANDO'
            self._tool_names={}
            self._tool_started={}
    def receive(self, raw:dict):
        obj=normalize_event(raw)
        if obj is None:return None
        with self.lock:
            if obj['event_id']:
                if obj['event_id'] in self._seen:return None
                self._seen.add(obj['event_id'])
                if len(self._seen)>10000:self._seen={obj['event_id']}
            if raw.get('created') and obj['ts']<self._wall_start:return None
            if obj['session'] and self._session and obj['session']!=self._session:
                return None
            tool_id=obj.get('tool_id')
            if tool_id and obj.get('tool'):
                self._tool_names[tool_id]=obj['tool']
            if tool_id and not obj.get('tool') and tool_id in self._tool_names:
                obj['tool']=self._tool_names[tool_id]
                if obj['type'].startswith('session.tool.'):
                    obj['label']+= ' · '+obj['tool'][:90]
            if obj['type']=='session.tool.input.started':self._status='PREPARANDO '+obj['tool'].upper()
            if obj['type']=='nexus.tool.preparing':self._status='PREPARANDO '+obj['tool'].upper()
            if tool_id and obj['type']=='session.tool.called':self._tool_started[tool_id]=obj['ts']
            if tool_id and obj['type'] in ('session.tool.success','session.tool.failed') and tool_id in self._tool_started:
                obj['duration']=round(max(0,obj['ts']-self._tool_started.pop(tool_id)),3)
            self.events.append(obj)
            if len(self.events)>350:
                self._attempt_index=max(0,self._attempt_index-(len(self.events)-350))
                self.events=self.events[-350:]
            if obj['blocked']:self._status='BLOQUEADO'
            elif obj['interrupted']:self._status='CANCELADO'
            elif obj['type']=='session.execution.failed':self._status='FALHOU'
            elif obj['type'] in ('permission.asked','form.created'):self._status='AGUARDANDO AUTORIZAÇÃO'
            elif obj['type']=='session.tool.called':self._status='EXECUTANDO '+obj['tool'].upper()
            elif obj['type']=='session.execution.started':self._status='EXECUTANDO'
            elif obj['type']=='session.execution.succeeded' and self._status not in ('BLOQUEADO','FALHOU'):
                self._status='VALIDANDO RESPOSTA FINAL'
            elif obj['type']=='permission.replied':self._status='EXECUTANDO'
        try:
            LOG.parent.mkdir(exist_ok=True,parents=True)
            if LOG.exists() and LOG.stat().st_size>8_000_000:
                LOG.replace(LOG.with_suffix('.previous.jsonl'))
            with LOG.open('a',encoding='utf-8') as f:f.write(json.dumps(obj,ensure_ascii=False)+'\n')
        except OSError:pass
        return obj
    def finish(self,state='CONCLUÍDO'):
        with self.lock:
            if self._status not in ('BLOQUEADO','FALHOU','CANCELADO'):
                self._status=state

    def state(self):
        with self.lock:return self._status
    def summary(self):
        with self.lock:
            failures=[x for x in self.events if x['failure']]
            return {'state':self._status,'failures':list(failures),
                    'executed':sum(x['type']=='session.tool.success' for x in self.events),
                    'completed':any(x['success'] for x in self.events[self._attempt_index:]),
                    'interrupted':any(x['interrupted'] for x in self.events),
                    'events':list(self.events)}
