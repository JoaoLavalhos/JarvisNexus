"""Public execution progress. Never stores or exposes model reasoning text."""
import threading
import time

class ExecutionProgress:
    def __init__(self, clock=time.monotonic):
        self.clock=clock;self.lock=threading.RLock();self.reset()

    def reset(self):
        with self.lock:
            self.started=self.last_activity=self.clock()
            self.phase='connecting';self.tool='';self.tool_id='';self.characters=0
            self.tools={};self.permissions=set();self.wait_started=None;self.wait_total=0.0;self.last_sample=0

    def observe(self, raw):
        et=raw.get('type') or raw.get('event') or ''
        data=raw.get('properties') or raw.get('data') or {}
        if not isinstance(data,dict):return None
        if et.startswith('form.'):
            form=data.get('form') or data
            fid=form.get('id') or data.get('formID') or data.get('id') or 'pending'
            data={**form,'id':'form:'+str(fid)}
        now=self.clock();sample=None
        with self.lock:
            if et.startswith('session.') or et.startswith('permission.') or et.startswith('form.'):
                # Stream transport traffic is not evidence of model/tool progress.
                if et not in ('session.status','session.idle','session.retry.scheduled'):
                    self.last_activity=now
            key=str(data.get('id') or '')
            if et=='session.tool.input.started':
                self.tools[key]={'tool':data.get('name') or data.get('tool') or 'ferramenta','characters':0,'started':now,'phase':'preparing'}
                self.tool_id=key;self.tool=self.tools[key]['tool'];self.characters=0;self.phase='preparing'
            elif et=='session.tool.input.delta':
                tool=self.tools.setdefault(key,{'tool':'ferramenta','characters':0,'started':now,'phase':'preparing'})
                tool['characters']+=len(data.get('delta') or '')
                self.tool_id=key;self.tool=tool['tool'];self.characters=tool['characters'];self.phase='preparing'
                if now-self.last_sample>=.6:
                    self.last_sample=now
                    sample={'type':'nexus.tool.preparing','properties':{'sessionID':data.get('sessionID'),'id':key,'tool':self.tool,
                        'message':f"Preparando {self.tool}: {self.characters:,} caracteres de argumentos recebidos; ainda não executada.",
                        'characters':self.characters,'elapsed':round(now-tool['started'],1)}}
            elif et=='session.tool.called':
                self.phase='waiting_question' if self.tool=='question' or data.get('tool')=='question' else 'running';self.tool_id=key
                self.tool=(self.tools.get(key) or {}).get('tool') or data.get('tool') or 'ferramenta'
                if self.tool=='question':self.phase='waiting_question'
                if key in self.tools:self.tools[key]['phase']='running'
            elif et in ('session.tool.success','session.tool.failed'):
                self.tools.pop(key,None)
                if self.tools:
                    key,tool=next(reversed(self.tools.items()))
                    self.phase=tool['phase'];self.tool=tool['tool'];self.tool_id=key;self.characters=tool['characters']
                else:self.phase='processing';self.tool='';self.tool_id=''
            elif et in ('permission.asked','form.created'):
                if not self.permissions:self.wait_started=now
                self.permissions.add(key or str(data.get('requestID') or data.get('permissionID') or 'pending'))
                self.phase='waiting_permission'
            elif et in ('permission.replied','permission.rejected','form.replied','form.cancelled'):
                permission=key or str(data.get('requestID') or data.get('permissionID') or '')
                if permission in self.permissions:self.permissions.remove(permission)
                elif self.permissions:self.permissions.pop()
                if not self.permissions and self.wait_started is not None:
                    self.wait_total+=now-self.wait_started;self.wait_started=None
                self.phase='running'
            elif et=='session.reasoning.started':self.phase='reasoning'
            elif et in ('session.text.started','session.text.delta'):self.phase='answering'
            elif et=='session.execution.succeeded':self.phase='validating'
            elif et=='session.execution.interrupted':self.phase='cancelled';self.permissions.clear()
        return sample

    def snapshot(self):
        with self.lock:
            return {'phase':('waiting_question' if any(p.startswith('form:') for p in self.permissions) else 'waiting_permission') if self.permissions else self.phase,'tool':self.tool,'tool_id':self.tool_id,'characters':self.characters,
                'elapsed':round(self.clock()-self.started,1),'silent_seconds':round(self.clock()-self.last_activity,1),
                'waiting_seconds':self.wait_total+(self.clock()-self.wait_started if self.wait_started is not None else 0)}

    def description(self):
        state=self.snapshot();phase=state['phase']
        if phase=='preparing':
            detail=f"{state['characters']:,} caracteres recebidos" if state['characters'] else 'aguardando argumentos da ferramenta'
            return f"Preparando {state['tool']} · {detail} · {state['elapsed']:.0f}s"
        labels={'connecting':'Conectando agente','running':'Executando '+state['tool'],'waiting_permission':'Aguardando sua autorização','waiting_question':'Aguardando sua resposta ao agente',
            'reasoning':'Planejando a próxima ação','answering':'Gerando resposta','validating':'Verificando resultado','processing':'Processando','cancelled':'Cancelado'}
        return labels.get(phase,'Executando')+f" · {state['elapsed']:.0f}s"
