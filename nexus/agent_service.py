"""Single persistent OpenCode session shared by the main text/voice UI.

No Qt access here. All callbacks are delivered via PyQt signals in MainWindow.
No calls to the OpenCode API from an audio callback or the Qt event loop.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import re
from pathlib import Path
import threading
import time
import traceback

from nexus.opencode_agent import OpenCodeAgent, AgentError
from nexus import diagnostics as diag
from nexus.agent_activity import ActivityLedger
from nexus.task_state import TaskState, Phase
from nexus.agent_progress import ExecutionProgress
from nexus.agent_verification import requested_lines, file_instruction, paths_from_input, verify_lines
import json


def clean_text(messages: list) -> str:
    """Extract the last assistant's actual answer, not reasoning or tool output.

    Supports the message/parts v1 shape and projected v2 'content' shape.
    """
    for msg in reversed(messages or []):
        if not isinstance(msg, dict): continue
        info = msg.get('info') if isinstance(msg.get('info'),dict) else msg
        if info.get('role') not in ('assistant',) and info.get('type') not in ('assistant',):
            continue
        pieces = []
        raw = msg.get('text')
        if isinstance(raw,str) and raw.strip(): pieces.append(raw.strip())
        content = msg.get('parts') or msg.get('content') or info.get('content') or []
        if isinstance(content,dict): content = [content]
        if isinstance(content,list):
            for item in content:
                if not isinstance(item,dict):continue
                if item.get('type') in ('text','output_text','assistant-text'):
                    txt=item.get('text') or item.get('value')
                    if isinstance(txt,str) and txt.strip():pieces.append(txt.strip())
        if pieces:
            return '\n'.join(dict.fromkeys(pieces)).strip()[-16_000:]
    return ''


def _assistant_message_id(msg: dict):
    """Stable assistant-message identity: user messages must NEVER count as a new answer."""
    if not isinstance(msg, dict):
        return None
    info = msg.get('info') if isinstance(msg.get('info'), dict) else msg
    role = info.get('role') or info.get('type')
    if role != 'assistant':
        return None
    answer = clean_text([msg])
    if not answer:
        return None
    ident = info.get('id') or msg.get('id') or info.get('messageID')
    if ident:
        return ('id', str(ident))
    # Fallback for projected API messages without IDs. Avoid treating old
    # messages as fresh just because a *user* turn appeared in the response.
    return ('text', answer)


def fresh_assistant_answer(messages: list, previous_assistant_ids: set):
    """Return only the newest genuinely NEW assistant message from this turn."""
    for msg in reversed(messages or []):
        marker = _assistant_message_id(msg)
        if marker is not None and marker not in previous_assistant_ids:
            return clean_text([msg]), marker
    return '', None


def is_brief_conversation(text: str) -> bool:
    """Conservative fast-path for simple chitchat only; tasks retain High and tools."""
    t = re.sub(r'\s+', ' ', (text or '').strip().lower()).strip(' .!?¡¿')
    if not t or len(t) > 110:
        return False
    # An action, a request for information, or any multi-step instruction is
    # NEVER downgraded to a cheaper reasoning setting.
    if any(w in t for w in ('abra ', 'abrir ', 'execut', 'faça ', 'faca ', 'pesquis',
            'analise ', 'altere ', 'crie ', 'escreva ', 'corrig', 'program',
            'arquivo', 'pastas', 'terminal', 'projeto', 'previsão', 'previsao',
            'notícia', 'noticia', 'explique ', 'compare ', 'calcule ', 'porque ', 'por que ')):
        return False
    return bool(re.match(
        r'^(?:jarvis[,! ]*)?(?:al[oô]|oi|ol[aá]|bom dia|boa tarde|boa noite|'
        r'voc[eê] (?:me )?(?:ouve|escuta)|voc[eê] consegue me ouvir|t[aá] me ouvindo|'
        r'consegue me ouvir|consegue me escutar|al[oô][, ]+t[aá] me ouvindo|'
        r'voc[eê] est[aá] me ouvindo|quem [eé] voc[eê]|'
        r'qual [eé] seu nome|como voc[eê] est[aá]|tudo bem|obrigad[oa]|'
        r'est[aá] funcionando|voc[eê] est[aá] funcionando)'
        r'(?:[,.! ]*(?:jarvis|senhor|por favor))?$', t))


class AgentService:
    def __init__(self, workspace: str, on_status, on_answer, on_error,
                 on_event, on_models):
        self.workspace=Path(workspace).resolve()
        self.on_status=on_status
        self.on_answer=on_answer
        self.on_error=on_error
        self.on_event=on_event
        self.on_models=on_models
        self.bridge=None
        self._pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='NexusOpenCode')
        self._lock=threading.Lock()
        self._busy=False
        self._closed=False
        self._connected=False
        self._pending=[]
        self._event_lock=threading.Lock()
        self._progress_seen=set()
        self._form_seen=set()
        self._permission_attempts={}
        self._user_declined=False
        self._mode='plan'
        self._model=None
        self._variant='high'
        self._quick_chat=True
        self.ledger=ActivityLedger()
        self._generation=0
        self._request_started=0.0
        self._max_runtime_sec=max(300,int(os.getenv('NEXUS_AGENT_MAX_SECONDS','1200')))
        self._cancel_requested=False
        self.progress=ExecutionProgress()
        self._task_file_paths=set()
        self._stall_seconds=max(30,int(os.getenv('NEXUS_AGENT_STALL_SECONDS','120')))
        self.task_state=TaskState(diag.LOGS/"agent_task.json", self.on_event)
        self._quarantined=False

    @property
    def busy(self):
        with self._lock:return self._busy or self._quarantined

    @property
    def elapsed_seconds(self):
        with self._lock:
            return round(time.monotonic()-self._request_started) if self._busy else 0

    @property
    def connected(self):
        with self._lock:return self._connected

    def configure(self, mode, model, variant, quick_chat=None):
        if mode not in ('plan','build'):
            raise ValueError('Modo agente inválido')
        with self._lock:
            self._mode=mode
            self._model=model if isinstance(model,dict) else None
            self._variant=variant if variant not in ('padrão','','default') else None
            if quick_chat is not None: self._quick_chat=bool(quick_chat)

    def start(self):
        if self._closed:return False
        def connect_safe():
            try:
                if self.connected and self.bridge and self.bridge.session_id and self.bridge.process and self.bridge.process.poll() is None:
                    self.on_models(self.bridge.get_models())
                    self.on_status('OpenCode conectado — catálogo de modelos atualizado')
                else:self._ensure_connected()
                if self._quarantined:
                    if self.bridge.status().get('type')=='idle':
                        self._quarantined=False
                        self.task_state.set(Phase.READY, 'Conexão verificada; agente pronto.')
            except Exception as exc:
                diag.error('opencode.refresh',exc)
                self.on_error('Não foi possível atualizar a conexão: '+str(exc))
        self._pool.submit(connect_safe)
        return True

    def reload_permissions(self):
        with self._lock:
            if self._busy:raise ValueError('Aguarde o término da tarefa para aplicar permissões.')
            self._busy=True
        def reload():
            try:
                if self.bridge:self.bridge.stop()
                with self._lock:self._connected=False
                self._ensure_connected()
                self.on_status('Permissões aplicadas em uma nova sessão OpenCode.')
            except Exception as exc:self.on_error('Permissões: '+str(exc))
            finally:
                with self._lock:self._busy=False
        self._pool.submit(reload)

    def _ensure_connected(self):
        if self._closed:raise AgentError('Serviço encerrado.')
        if self.bridge and self.bridge.session_id and self.bridge.process and self.bridge.process.poll() is None:
            return
        self.on_status('Inicializando agente OpenCode...')
        try:
            if self.bridge:
                try:self.bridge.stop()
                except Exception:pass
            self.bridge=OpenCodeAgent(self.workspace)
            health=self.bridge.start(self._handle_event)
            if self._closed:
                self.bridge.stop()
                raise AgentError('Serviço encerrado durante a conexão.')
            self.bridge.new_session('JARVIS NEXUS AGENT V1.9')
            models=self.bridge.get_models()
            with self._lock:self._connected=True
            target=next((m for m in models if m.get('id')=='gpt-6-sol'),None)
            if target:
                with self._lock:
                    if self._model is None:self._model=target
            self.on_models(models)
            self.on_status(f'OpenCode conectado ({health.get("version","v?")}), sessão ativa')
            diag.info('opencode.session.connected', version=health.get('version'), api=self.bridge.api_version)
        except Exception as exc:
            with self._lock:self._connected=False
            diag.error('opencode.connect',exc)
            self.on_error(f'Falha ao conectar OpenCode: {exc}')
            raise

    def _handle_event(self,event):
        """Watch the actual execution result, not merely a tool-free text fragment."""
        if self._closed:return
        event_id=event.get('id')
        created=event.get('created')
        if isinstance(created,(int,float)):
            seconds=created/1000 if created>1e11 else created
            if self.ledger._wall_start and seconds<self.ledger._wall_start:return
        if event_id:
            with self._event_lock:
                if event_id in self._progress_seen:return
                self._progress_seen.add(event_id)
                if len(self._progress_seen)>12000:self._progress_seen={event_id}
        raw_data=event.get('properties') or event.get('data') or {}
        sid=raw_data.get('sessionID') if isinstance(raw_data,dict) else None
        if sid and self.bridge and self.bridge.session_id and sid!=self.bridge.session_id:return
        if event.get('type')=='form.created':
            form=raw_data.get('form',raw_data)
            if self.bridge and form.get('sessionID')!=self.bridge.session_id:return
            fid=form.get('id')
            if fid in self._form_seen:return
            self._form_seen.add(fid)
        sample=self.progress.observe(event)
        if sample:
            progress_item=self.ledger.receive(sample)
            if progress_item:self.on_event({'type':'nexus.activity','properties':progress_item})
            self.on_status(self.progress.description())
        if event.get('type')=='session.tool.called' and isinstance(raw_data,dict):
            self._task_file_paths.update(paths_from_input(raw_data.get('input') or raw_data.get('args') or {},self.workspace))
        # Ephemeral token chunks are counted above, not persisted or forwarded to Qt.
        if (event.get('type') or event.get('event')) in ('session.tool.input.delta','session.reasoning.delta','session.text.delta'):return
        item=self.ledger.receive(event)
        if item and item.get('failure'):
            diag.warning('agent.execution.event_failed', type=item['type'], reason=item['detail'][:250])
        if item and item.get('type') in ('session.tool.input.started','session.reasoning.started','session.text.started','session.tool.called','session.tool.progress',
                      'permission.asked','session.execution.started','session.execution.failed',
                      'permission.rejected','session.execution.succeeded'):
            self.on_status(item['label'] + ((': '+item['detail'][:100]) if item['detail'] and item['failure'] else ''))
        if item:
            self.on_event({'type':'nexus.activity','properties':item})
        self.on_event(event)
        if item and self.busy and not self._cancel_requested:
            if item['type'] in ('permission.asked','form.created'):self.task_state.set(Phase.WAITING_PERMISSION)
            elif item['type'] in ('permission.replied','form.replied','form.cancelled'):self.task_state.set(Phase.RUNNING)

    def submit(self,text:str,source='texto', include_screen=False, image=None, target_file=None) -> bool:
        text=(text or '').strip()
        if not text:return False
        if include_screen and image is None:
            self.on_status('Captura não enviada: é necessária a prévia aprovada no painel.')
            return False
        with self._lock:
            if self._busy or self._closed or self._quarantined:
                self.on_status('NÃO ENVIADO: agente ocupado. Aguarde a conclusão ou clique em PARAR TAREFA.')
                diag.warning('agent.request.rejected_busy',chars=len(text))
                return False
            self._busy=True
            self._cancel_requested=False
            self._request_started=time.monotonic()
            mode,model,variant,quick_chat=self._mode,self._model,self._variant,self._quick_chat
        diag.info('agent.request', origin=source, chars=len(text), mode=mode,
                  model=(model or {}).get('id','padrão'))
        self.progress.reset();self._task_file_paths=set();self._user_declined=False
        if target_file:self._task_file_paths.add(Path(target_file).resolve())
        self.task_state.begin(model)
        self._pool.submit(self._run,text,mode,model,variant,source,quick_chat,include_screen,image,target_file)
        return True

    def _run(self,text,mode,model,variant,source,quick_chat,include_screen=False,image=None,target_file=None,_verification_retry=0,_deadline=None):
        try:
            t0=time.perf_counter()
            self._ensure_connected()
            if self._cancel_requested:raise AgentError('Tarefa cancelada antes do envio.')
            if model is None:model=self._model
            if model is None and hasattr(self.bridge,'default_model'):
                model=self.bridge.default_model()
            with self.task_state.lock:self.task_state.value['model']=(model or {}).get('id','não informado')
            self.on_event({'type':'nexus.model','properties':{'provider':(model or {}).get('providerID','OpenCode'),'model':(model or {}).get('id','padrão não informado')}})
            connection_ms=round((time.perf_counter()-t0)*1000)
            short=quick_chat and mode=='plan' and is_brief_conversation(text)
            if short and model and model.get('variants') and 'low' not in model['variants']:
                short=False  # Do not request a reasoning level absent from the catalog.
            effective_variant=('low' if short and variant in (None,'high','xhigh','max') else variant)
            self.on_status('GPT: conversa curta (Low)' if short else f'OpenCode: {mode} executando ({source})')
            started=time.perf_counter()
            previous=self.bridge.messages()
            if _verification_retry:self.ledger.begin(self.bridge.session_id or "",preserve=True)
            else:self.ledger.begin(self.bridge.session_id or "")
            if target_file:self._task_file_paths.add(Path(target_file).resolve())
            previous_users={str((m.get('info') or m).get('id') or '') for m in previous
                if ((m.get('info') or m).get('role') or (m.get('info') or m).get('type'))=='user'}
            prior_assistants={mark for m in previous if (mark:=_assistant_message_id(m)) is not None}
            # Prompt controls user-facing persona, not the model's provider identity.
            # It is transient and does not modify the user's OpenCode global config.
            instruction=(
                'Você é JARVIS NEXUS, assistente pessoal de voz em um computador Windows. '
                'A mensagem a seguir foi transcrita do microfone pelo Groq, se a origem for voz. '
                'Se o usuário perguntar se você consegue ouvi-lo, explique naturalmente '
                'que recebeu o texto da voz dele pelo microfone. Não mencione câmera '
                'a menos que a pessoa tenha perguntado sobre câmera. '
                'Não se apresente como nome de modelo (por exemplo GPT-6 Sol); '
                'GPT é o motor de inteligência e JARVIS NEXUS é o nome do assistente. '
                f'Identidade técnica da requisição: provedor={(model or {}).get("providerID","padrão do OpenCode")}; modelo={(model or {}).get("id","não informado pelo servidor")}. '
                'Quando perguntarem seu modelo, informe esse identificador configurado. Não invente revisão interna. '
                'Responda sempre em português brasileiro, de maneira natural e objetiva; '
                'use o tratamento senhor quando adequado, sem repetir em toda frase. '
                'Se a solicitação for apenas uma saudação ou confirmação de áudio, '
                'responda em uma única frase curta, sem usar ferramentas. '
                'Para perguntas sobre a tela, considere somente imagens efetivamente recebidas como anexo; ' 
                'nunca alegue que está vendo a tela ao vivo sem captura. ' 
                'Para tarefas de verdade, execute apenas as ações autorizadas, '
                'relate resultados verificados e não invente sucessos. '
                'Em modo plan, não altere arquivos. '+
                file_instruction(text,target_file)+
                ('Uma captura aprovada foi anexada a ESTE pedido. Analise essa imagem estática e descreva o que nela aparece, sem pedir outra captura nem alegar visão contínua. ' if image is not None else '')+
                f'Origem da mensagem: {source}.\nMensagem do usuário: '
            )
            if include_screen and image is None:
                raise AgentError('Captura sem aprovação da prévia; nada foi enviado.')
            # Keep compatible with existing text-only bridges and test mocks;
            # request image attachment only when an explicit capture exists.
            if image is None:
                self.bridge.prompt(instruction+text,agent=mode,model=model,
                                   variant=effective_variant)
            else:
                self.bridge.prompt(instruction+text,agent=mode,model=model,
                                   variant=effective_variant,image=image)
            if image is not None:
                receipt=self.bridge.verify_image_attachment(image,previous_users,cancelled=lambda:self._cancel_requested) if hasattr(self.bridge,'verify_image_attachment') else {'bytes':len(image)}
                self._handle_event({'type':'nexus.screen.attached','properties':{'sessionID':self.bridge.session_id,'message':f"Captura confirmada no pedido: {receipt['bytes']} bytes. Aguardando análise visual."}})
                diag.info('agent.screen.delivery.confirmed',bytes=receipt['bytes'],message_id=receipt.get('message_id'))
                self.on_status('Captura recebida pelo modelo; analisando a imagem')
            t_submitted=time.perf_counter()
            diag.info('agent.prompt.submitted', submit_seconds=round(t_submitted-started,3),
                      variant=effective_variant or 'default', quick_chat=short)
            idle_checks=0; latest_answer=''; last_marker=None
            messages=[]
            last_progress_text=''
            # OpenCode v2 only signals completion when the session leaves /active.
            # Require new assistant messages, NOT a newly appended user message.
            deadline=_deadline if _deadline is not None else time.monotonic()+self._max_runtime_sec
            last_heartbeat=time.monotonic()
            while time.monotonic()<deadline+self.progress.snapshot()['waiting_seconds'] and not self._closed:
                time.sleep(.65)
                if self._cancel_requested:
                    raise AgentError('Tarefa cancelada a pedido do usuário.')
                now=time.monotonic()
                if now-last_heartbeat>=4:
                    self.on_status(self.progress.description())
                    if hasattr(self.bridge,'pending_forms'):
                        try:
                            for form in self.bridge.pending_forms():self._handle_event({'type':'form.created','properties':{'form':form}})
                        except Exception as form_error:diag.warning('agent.forms.poll_failed',reason=type(form_error).__name__)
                    if hasattr(self.bridge,'pending_permissions'):
                        try:
                            for permission in self.bridge.pending_permissions():
                                pid=permission.get('id')
                                self._handle_event({'id':f'pending-permission:{pid}:{self._permission_attempts.get(pid,0)}','type':'permission.asked','properties':permission})
                        except Exception as permission_error:diag.warning('agent.permissions.poll_failed',reason=type(permission_error).__name__)
                    diag.info('agent.heartbeat',seconds=round(now-started,1),state=self.ledger.state())
                    last_heartbeat=now
                try:
                    status=self.bridge.status() or {}
                    messages=self.bridge.messages()
                except Exception as exc:
                    diag.warning('agent.poll.failed',reason=type(exc).__name__)
                    continue
                fresh,marker=fresh_assistant_answer(messages,prior_assistants)
                if fresh:
                    latest_answer,last_marker=fresh,marker
                state=status.get('type') if isinstance(status,dict) else ''
                if fresh and state!='idle' and fresh!=last_progress_text:
                    self._handle_event({'type':'nexus.commentary','properties':{'sessionID':self.bridge.session_id,'message':fresh[:8000]}})
                    last_progress_text=fresh
                ledger=self.ledger.summary()
                progress=self.progress.snapshot()
                if state=='busy' and progress['phase'] not in ('waiting_permission','waiting_question') and progress['silent_seconds']>self._stall_seconds:
                    raise TimeoutError(f"O agente está sem progresso confirmado há {progress['silent_seconds']:.0f}s ({progress['phase']}). Interrompendo e verificando o servidor; veja Execução do agente.")
                # When the server is idle after a rejected permission, a prior
                # "I will check" text fragment is NOT a successful answer.
                if state=='idle' and (latest_answer or ledger['failures'] or ledger.get('interrupted')):
                    idle_checks+=1
                    if idle_checks>=2:break
                else:
                    idle_checks=0
                if self.bridge.process and self.bridge.process.poll() is not None:
                    raise AgentError('Processo OpenCode encerrou inesperadamente')
            else:
                # Avoid leaving a dangerous orphan editing files after the UI
                # incorrectly declares it free to accept a new task.
                raise TimeoutError(f'O agente atingiu {self._max_runtime_sec}s sem concluir. A interrupção será verificada; consulte o estado no monitor.')
            elapsed=time.perf_counter()-started
            outcome=self.ledger.summary()
            if not outcome['completed'] and hasattr(self.bridge,'recover_events'):
                self.bridge.recover_events(self._handle_event)
                outcome=self.ledger.summary()
            if outcome['failures']:
                problems=outcome['failures']
                last=problems[-1]
                blocked=any(x['blocked'] for x in problems)
                fatal=any(x['type'] in ('session.execution.failed','session.error') for x in problems)
                cause=last.get('detail') or last['label']
                if blocked or fatal or not (outcome['completed'] and latest_answer):
                    prefix='TAREFA BLOQUEADA' if blocked else 'TAREFA COM FALHAS'
                    # Do not turn an intention ("vou verificar") into a success.
                    if latest_answer:
                        self.on_status('O agente produziu texto, mas encontrou uma falha. A tarefa não foi concluída.')
                    raise AgentError(f'{prefix}: {cause}. '
                                     'Confira a linha do tempo de ferramentas e a pasta autorizada.')
                # Recoverable tool failure followed by a verified execution success:
                # preserve a visible warning, rather than silently claiming perfection.
                latest_answer=('CONCLUÍDO COM AVISOS: uma ferramenta falhou durante a execução. '
                               'Verifique o monitor para detalhes.\n\n'+latest_answer)
            if self._cancel_requested or outcome.get('interrupted'):
                raise AgentError('Tarefa cancelada a pedido do usuário.')
            terminal_message=False
            for message in reversed(messages):
                info=message.get('info',message)
                if _assistant_message_id(message)==last_marker:
                    if info.get('error') or info.get('finish') in ('error','length','content-filter'):
                        raise AgentError('O modelo terminou com erro ou resposta incompleta: '+str(info.get('error') or info.get('finish')))
                    terminal_message=info.get('finish')=='stop' and bool(info.get('time',{}).get('completed'))
                    break
            if not outcome['completed'] and not terminal_message:
                raise AgentError('Sessão ociosa sem confirmação de conclusão. Texto parcial não é sucesso; consulte o monitor.')
            if not latest_answer:
                raise AgentError('O agente terminou sem uma resposta final. Veja as etapas no Monitor do agente.')
            count=requested_lines(text)
            if count:
                evidence,verification_error=verify_lines(count,[target_file] if target_file else self._task_file_paths)
                self._handle_event({'type':'nexus.verification','properties':{'sessionID':self.bridge.session_id,
                    'message':json.dumps({'required_lines':count,'files':evidence,'error':verification_error},ensure_ascii=False,indent=2)}})
                if verification_error:
                    if _verification_retry==0 and not self._user_declined and time.monotonic()+10<deadline+self.progress.snapshot()['waiting_seconds']:
                        self.on_status('A contagem ainda não atende ao pedido. Solicitando uma correção verificada ao agente.')
                        correction=text+'\n\nA verificação local encontrou: '+verification_error+' Corrija o arquivo de fato com um pequeno script e confira a contagem. Não crie uma cópia com outro nome.'
                        return self._run(correction,mode,model,variant,source,quick_chat,False,None,target_file,1,deadline)
                    raise AgentError(verification_error)
                latest_answer+='\n\nVerificação local: '+ '; '.join(f"{item['path']} — {item['lines']} linhas" for item in evidence)
            self.ledger.finish('CONCLUÍDO COM AVISOS' if outcome['failures'] else 'CONCLUÍDO')
            self.task_state.set(Phase.SUCCEEDED)
            if hasattr(self.bridge,'diff'):
                try:
                    changes=self.bridge.diff()
                    if changes:self._handle_event({'type':'nexus.diff','properties':{'sessionID':self.bridge.session_id,'diff':changes}})
                except Exception as exc:diag.warning('agent.diff.unavailable',reason=type(exc).__name__)
            self.on_answer(latest_answer,source,elapsed)
            self.on_status(f'GPT: {elapsed:.2f}s (conexão {connection_ms}ms, {effective_variant or "default"})')
            diag.info('agent.answer', seconds=round(elapsed,2),chars=len(latest_answer),
                      variant=effective_variant or 'default', short=short,
                      connect_ms=connection_ms, new_assistant_marker=str(last_marker)[:100])
        except Exception as exc:
            diag.error('agent.run',exc)
            if self._cancel_requested or isinstance(exc,TimeoutError):
                stopped=self._confirm_stopped()
            else:
                try: stopped=self.bridge is None or self.bridge.status().get('type')=='idle'
                except Exception: stopped=False
                if not stopped: stopped=self._confirm_stopped()
            self._quarantined=not stopped
            message=str(exc)
            if not stopped:message+=' Não foi possível confirmar a interrupção. Novas tarefas estão bloqueadas; use PARAR ou reconecte e verifique o estado.'
            terminal=Phase.RECOVERY_REQUIRED if not stopped else (Phase.CANCELLED if self._cancel_requested else Phase.FAILED)
            self.ledger.finish('CANCELADO' if self._cancel_requested else 'FALHOU')
            self.task_state.set(terminal,diag.sanitize(message))
            self.on_error(message)
            if stopped and self.bridge and hasattr(self.bridge,'diff'):
                try:
                    changes=self.bridge.diff()
                    if changes:self._handle_event({'type':'nexus.diff','properties':{'sessionID':self.bridge.session_id,'diff':changes}})
                except Exception as diff_error:diag.warning('agent.partial_diff.unavailable',reason=type(diff_error).__name__)
            self.on_status(('CANCELADO: ' if self._cancel_requested else 'FALHOU: ')+message[:160])
        finally:
            with self._lock:self._busy=False

    def _confirm_stopped(self):
        bridge=self.bridge
        if not bridge:return True
        try:
            if hasattr(bridge,'interrupt_and_wait'):
                stopped=bridge.interrupt_and_wait(timeout=8)
                if stopped:return True
            else:
                bridge.abort()
                if bridge.status().get('type')=='idle':return True
            bridge.stop()
            proc=bridge.process
            stopped=proc is None or proc.poll() is not None
            if stopped:
                with self._lock:self._connected=False
            return stopped
        except Exception as exc:
            diag.warning('agent.stop.unconfirmed',reason=type(exc).__name__)
            return False

    def cancel(self):
        if not self.busy:return
        self._cancel_requested=True
        self.task_state.set(Phase.STOPPING, 'Aguardando confirmação de interrupção do servidor.')
        if self._quarantined and not self._busy:
            def recover_stop():
                stopped=self._confirm_stopped()
                self._quarantined=not stopped
                self.task_state.set(Phase.CANCELLED if stopped else Phase.RECOVERY_REQUIRED, 'Interrupção confirmada.' if stopped else 'Interrupção ainda não confirmada.')
                self.on_status('Interrupção confirmada.' if stopped else 'Interrupção não confirmada; tarefas continuam bloqueadas.')
            self._pool.submit(recover_stop)
        # The worker owns completion and verifies interruption before releasing busy.
        self.on_status('Cancelamento solicitado; aguardando a interrupção efetiva.')

    def reply_form(self,form_id,answer):
        if not self.bridge:return
        if answer is None:
            self._user_declined=True;self.cancel()
        elif any(str(value).lower() in ('não executar','nao executar','não autorizar','negar','cancelar tarefa') for value in answer.values()):
            self._user_declined=True
        def run():
            try:
                self.bridge.respond_form(form_id,answer)
                self._handle_event({'type':'form.cancelled' if answer is None else 'form.replied',
                    'properties':{'id':form_id,'formID':form_id,'sessionID':self.bridge.session_id}})
            except Exception as exc:
                self.on_status('Não foi possível enviar a resposta: '+str(exc))
                self._form_seen.discard(form_id)
        threading.Thread(target=run,daemon=True,name='AgentFormReply').start()

    def reply_permission(self,pid,approved):
        if not self.bridge:return
        def run():
            try:
                self.bridge.respond_permission(pid,bool(approved))
                diag.info('agent.permission.replied',approved=bool(approved))
            except Exception as exc:
                diag.error('agent.permission.reply',exc)
                self._permission_attempts[pid]=self._permission_attempts.get(pid,0)+1
                self.on_event({'type':'nexus.permission.reply_failed','properties':{'id':pid}})
                self.on_status(f'Não foi possível enviar a permissão: {exc}. O pedido será exibido novamente.')
        threading.Thread(target=run,daemon=True,name='AgentPermission').start()

    def shutdown(self):
        self._closed=True
        # Never block Qt UI thread on a Windows process shutdown.
        br=self.bridge
        if br:
            threading.Thread(target=br.stop,daemon=True,name='AgentShutdown').start()
        self._pool.shutdown(wait=False,cancel_futures=True)
