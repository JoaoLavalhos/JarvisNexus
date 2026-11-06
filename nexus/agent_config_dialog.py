"""NEXUS Agent cockpit: independent connection, agent options and live tool timeline.

No OpenCode client is owned by this dialog. Closing it cannot stop a task.
"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
import json
from nexus.agent_permissions import load_rules, save_rules, validate_rules
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,
    QLineEdit,QPushButton,QFileDialog,QMessageBox,QCheckBox,QTabWidget,QWidget,
    QTreeWidget,QTreeWidgetItem,QPlainTextEdit,QHeaderView)
from nexus import diagnostics as diag
from memory.config_manager import get_voice, AVAILABLE_VOICES

_STYLE='''
 QDialog{background:#061321;color:#d5f7ff;font:10pt "Segoe UI";}
 QLineEdit,QComboBox,QPlainTextEdit,QTreeWidget{background:#0b2030;color:#e5fcff;
     padding:7px;border:1px solid #256583;border-radius:5px;}
 QPushButton{background:#14455f;color:white;padding:8px;border:1px solid #3796ac;border-radius:5px;}
 QPushButton:hover{background:#20617b;} QLabel{color:#ade6ed;}
 QCheckBox{color:#ade6ed;}
 QTabBar::tab{background:#102b40;color:#c6eef7;padding:8px;}
 QTabBar::tab:selected{background:#1a5268;color:white;}
 QTabWidget::pane{border:1px solid #20536c;}
'''

class AgentConfigDialog(QDialog):
    def __init__(self,parent):
        super().__init__(parent)
        self.window=parent
        self.setWindowTitle('JARVIS NEXUS V1.9 — CENTRAL DE OPERAÇÕES / OPENCODE')
        self.resize(1090,790)
        self.setStyleSheet(_STYLE)
        root=QVBoxLayout(self);root.setSpacing(12)
        header=QHBoxLayout()
        name=QLabel('◈  NEXUS AGENT · CENTRAL DE OPERAÇÕES');name.setStyleSheet('font: bold 18pt "Segoe UI"; color:#4ad7f2;')
        header.addWidget(name);header.addStretch()
        self.connection=QLabel('DESLIGADO');self.connection.setStyleSheet('color:#ffb967;font-weight:bold;')
        header.addWidget(self.connection);root.addLayout(header)
        self.status=QLabel('Selecione Conectar Agente. O processo pertence ao NEXUS, não a esta janela.')
        self.status.setWordWrap(True);root.addWidget(self.status)

        bar=QHBoxLayout()
        connect=QPushButton('CONECTAR / ATUALIZAR MODELOS');connect.clicked.connect(self.connect);bar.addWidget(connect)
        stop=QPushButton('PARAR TAREFA');stop.clicked.connect(parent._agent_cancel_on_ui);bar.addWidget(stop)
        logs=QPushButton('ABRIR LOGS');logs.clicked.connect(self.open_logs);bar.addWidget(logs)
        self.refresh=QPushButton('ATUALIZAR ESTADO');self.refresh.clicked.connect(self.refresh_status);bar.addWidget(self.refresh)
        root.addLayout(bar)
        self.tabs=QTabWidget(self);root.addWidget(self.tabs,1)
        self._make_activity_tab()
        self._make_config_tab()
        self._make_permissions_tab()
        self._monitor_tick=QTimer(self)
        self._monitor_tick.timeout.connect(self._update_live_task)
        self._monitor_tick.start(1000)

        svc=parent._agent_service
        if svc and svc.connected:self.connection.setText('CONECTADO · SESSÃO ATIVA')
        if svc and svc.busy:self.status.setText('Tarefa em execução. Veja as ferramentas na linha do tempo.')
        if svc and svc.bridge and svc.bridge.session_id:
            self.session_lbl.setText('Sessão: '+str(svc.bridge.session_id))
        if svc:
            for event in svc.ledger.summary()['events']:
                self.append_activity(event)

    def _make_activity_tab(self):
        w=QWidget();lay=QVBoxLayout(w);lay.setSpacing(9)
        intro=QLabel('Este monitor mostra o que o agente executa. Uma etapa ou mensagem parcial NÃO equivale a trabalho concluído.')
        intro.setWordWrap(True);lay.addWidget(intro)
        self.session_lbl=QLabel('Sessão: nenhuma');lay.addWidget(self.session_lbl)
        self.task_runtime=QLabel('Sem tarefas ativas')
        self.task_runtime.setStyleSheet('color:#49dfcf;font-weight:bold;')
        lay.addWidget(self.task_runtime)
        self.filter=QComboBox()
        self.filter.addItems(['Todos','Ferramentas','Erros','Permissões','Alterações','Conexão'])
        self.filter.currentIndexChanged.connect(self._filter_events)
        lay.addWidget(self.filter)
        self.table=QTreeWidget();self.table.setHeaderLabels(['Hora','Estado / ferramenta','Detalhes','Duração'])
        self.table.setColumnWidth(0,90);self.table.setColumnWidth(1,255)
        self.table.header().setStretchLastSection(False)
        self.table.header().setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch)
        self.table.header().setSectionResizeMode(3,QHeaderView.ResizeMode.ResizeToContents)
        self.table.setRootIsDecorated(False);self.table.setAlternatingRowColors(True)
        lay.addWidget(self.table,1)
        self.tool_details=QPlainTextEdit()
        self.tool_details.setReadOnly(True)
        self.tool_details.setMinimumHeight(170)
        self.tool_details.setPlaceholderText('Selecione um evento para inspecionar os argumentos ou o motivo da falha.')
        self.table.currentItemChanged.connect(self._select_event)
        lay.addWidget(self.tool_details)
        explain=QPushButton('PERMISSÕES E ACESSO À TELA');explain.clicked.connect(self.explain_permissions);lay.addWidget(explain)
        self.tabs.addTab(w,'ATIVIDADE E FERRAMENTAS')

    def _make_config_tab(self):
        w=QWidget();lay=QVBoxLayout(w)
        lay.addWidget(QLabel('Pasta de trabalho: o agente lê e executa ferramentas aqui. Para outras pastas, deve pedir permissão.'))
        pathrow=QHBoxLayout();self.path=QLineEdit(str(self.window._agent_workspace));pathrow.addWidget(self.path)
        pick=QPushButton('ESCOLHER PASTA');pick.clicked.connect(self.pick);pathrow.addWidget(pick)
        lay.addLayout(pathrow)
        lay.addWidget(QLabel('Modo de execução:'))
        self.mode=QComboBox();self.mode.addItems(['plan','build']);lay.addWidget(self.mode)
        svc=self.window._agent_service
        if svc and svc._mode in ('plan','build'):self.mode.setCurrentText(svc._mode)
        lay.addWidget(QLabel('Motor de raciocínio (independente da voz):'))
        self.model=QComboBox();self.model.addItem('Padrão do OpenCode',None)
        lay.addWidget(self.model)
        lay.addWidget(QLabel('Nível de raciocínio:'))
        self.variant=QComboBox();self.variant.addItems(['padrão','low','medium','high','xhigh','max'])
        self.variant.setCurrentText((svc._variant if svc else None) or 'high')
        lay.addWidget(self.variant)
        self.fast_chat=QCheckBox('Conversas simples: usar raciocínio Low quando o modelo permitir')
        self.fast_chat.setChecked(svc._quick_chat if svc else True)
        lay.addWidget(self.fast_chat)
        lay.addWidget(QLabel('Voz de saída: funciona independentemente do GPT, Gemini ou modo Plan/Build.'))
        self.voice_provider=QComboBox()
        self.voice_provider.addItem('Gemini Live — voz da resposta GPT', 'gemini_live')
        self.voice_provider.addItem('Somente texto — sem voz', 'none')
        lay.addWidget(self.voice_provider)
        self.voice_name=QComboBox();self.voice_name.addItems(AVAILABLE_VOICES)
        lay.addWidget(QLabel('Voz Gemini Live (Charon preservada):'))
        lay.addWidget(self.voice_name)
        self.tts_model=QComboBox()
        self.tts_model.addItem('Modelo Live automático — mesma seleção da conversa',None)
        self.tts_model.setEnabled(False)
        lay.addWidget(self.tts_model)
        voice=self.window._agent_voice
        if voice:
            self.voice_provider.setCurrentIndex(max(0,self.voice_provider.findData(voice.provider)))
            self.voice_name.setCurrentText(voice.voice if voice.voice in AVAILABLE_VOICES else get_voice())
            self.tts_model.setCurrentIndex(max(0,self.tts_model.findData(voice.gemini_model)))
        else:self.voice_name.setCurrentText(get_voice())
        self.voice_provider.currentIndexChanged.connect(self._toggle_voice)
        self._toggle_voice()
        self.load_models(self.window._agent_catalog)
        if svc and svc._model:
            for i in range(self.model.count()):
                obj=self.model.itemData(i)
                if obj and obj.get('id')==svc._model.get('id'):
                    self.model.setCurrentIndex(i);break
        savebar=QHBoxLayout()
        save=QPushButton('SALVAR MODELO, PERMISSÕES E VOZ');save.clicked.connect(self.save);savebar.addWidget(save)
        test=QPushButton('TESTAR A VOZ SELECIONADA');test.clicked.connect(self.test_voice);savebar.addWidget(test)
        lay.addLayout(savebar)
        lay.addWidget(QLabel('Gemini Live tem limites e pode alterar palavras. O texto GPT permanece intacto; a transcrição da voz é conferida.'))
        lay.addStretch()
        self.tabs.addTab(w,'MODELOS, VOZ E PERMISSÕES')

    def _toggle_voice(self):
        active=self.voice_provider.currentData()=='gemini_live'
        self.voice_name.setEnabled(active);self.tts_model.setEnabled(False)

    def load_models(self,models):
        selected=self.model.currentData() if hasattr(self,'model') else None
        self.model.clear();self.model.addItem('Padrão do OpenCode',None)
        for m in models or []:
            self.model.addItem(f"{m.get('name',m.get('id'))} — {m.get('providerID','')}",m)
        if selected:
            for i in range(self.model.count()):
                v=self.model.itemData(i)
                if v and v.get('id')==selected.get('id'):
                    self.model.setCurrentIndex(i);break

    def _make_permissions_tab(self):
        widget=QWidget();layout=QVBoxLayout(widget)
        info=QLabel('Regras aplicadas somente ao servidor deste JARVIS. A última regra compatível prevalece. '
            'allow permite, ask pergunta e deny bloqueia. Use recursos específicos para comandos e pastas externas. '
            'Salvar regras abre uma nova sessão; a tarefa atual deve estar concluída.')
        info.setWordWrap(True);layout.addWidget(info)
        self.rules=QPlainTextEdit()
        self.rules.setPlainText(json.dumps(load_rules(self.window._agent_workspace),ensure_ascii=False,indent=2))
        layout.addWidget(self.rules,1)
        save=QPushButton('APLICAR REGRAS E RECONECTAR');save.clicked.connect(self._save_permissions);layout.addWidget(save)
        self.tabs.addTab(widget,'REGRAS DE PERMISSÃO')

    def _save_permissions(self):
        try:
            service=self.window._ensure_agent_service()
            if service.busy:raise ValueError('Aguarde a conclusão ou cancele a tarefa antes de alterar regras.')
            rules=validate_rules(json.loads(self.rules.toPlainText()))
            save_rules(self.window._agent_workspace,rules)
            service.reload_permissions()
            self.set_status('Regras salvas. Aplicando em nova sessão…')
        except Exception as exc:QMessageBox.warning(self,'Permissões',str(exc))

    def _select_event(self, row, _previous):
        if row is None:return
        payload=row.data(0,Qt.ItemDataRole.UserRole)
        if isinstance(payload,dict):
            self.tool_details.setPlainText(json.dumps(payload,ensure_ascii=False,indent=2))

    def _filter_events(self):
        selected=self.filter.currentText()
        for i in range(self.table.topLevelItemCount()):
            row=self.table.topLevelItem(i)
            item=row.data(0,Qt.ItemDataRole.UserRole) or {}
            et=item.get('type','')
            show=(selected=='Todos' or
                selected=='Ferramentas' and '.tool.' in et or
                selected=='Erros' and item.get('failure') or
                selected=='Permissões' and et.startswith('permission.') or
                selected=='Alterações' and (et=='nexus.diff' or item.get('tool') in ('edit','apply_patch','write')) or
                selected=='Conexão' and et.startswith('nexus.stream.'))
            row.setHidden(not show)

    def _update_live_task(self):
        svc=self.window._agent_service
        if not svc:
            self.task_runtime.setText('OpenCode desconectado')
            return
        if svc._quarantined:
            self.task_runtime.setText('ESTADO INCERTO · novas tarefas bloqueadas. Use PARAR ou CONECTAR para verificar.')
        elif svc.busy:
            duration=svc.elapsed_seconds
            state=svc.ledger.state()
            summ=svc.ledger.summary()
            self.task_runtime.setText(f'{state} · {duration}s · {summ["executed"]} ferramentas concluídas · '
              f'{len(summ["failures"])} avisos/erros')
        else:
            self.task_runtime.setText('Sessão pronta · '+svc.ledger.state())
        self.connection.setText('CONECTADO' if svc.connected else 'DESCONECTADO')

    def append_activity(self,item):
        if not isinstance(item,dict):return
        t=datetime.fromtimestamp(item.get('ts',0)).strftime('%H:%M:%S')
        duration=str(item['duration'])+'s' if item.get('duration') is not None else '—'
        row=QTreeWidgetItem([t,str(item.get('label',''))[:130],str(item.get('detail',''))[:280],duration])
        row.setData(0,Qt.ItemDataRole.UserRole,item)
        row.setToolTip(2,str(item.get('detail',''))[:1800])
        if item.get('failure'):
            from PyQt6.QtGui import QColor
            row.setForeground(1,QColor('#ff897e'))
        elif item.get('success'):
            from PyQt6.QtGui import QColor
            row.setForeground(1,QColor('#7de1b5'))
        self.table.addTopLevelItem(row)
        self._filter_events()
        if not row.isHidden():self.table.scrollToItem(row)
        while self.table.topLevelItemCount()>280:
            self.table.takeTopLevelItem(0)

    def set_status(self,text):
        self.status.setText(str(text)[:650])
        service=self.window._agent_service
        if service and service.connected:
            state=service.ledger.state()
            self.connection.setText('CONECTADO · '+state)
            if service.bridge:self.session_lbl.setText('Sessão: '+str(service.bridge.session_id))
        else:self.connection.setText('DESCONECTADO')

    def refresh_status(self):
        service=self.window._agent_service
        if not service:
            self.set_status('Nenhum agente iniciado. Use CONECTAR.')
            return
        self.set_status(('Executando' if service.busy else 'Livre')+' · '+('conectado' if service.connected else 'desconectado'))

    def connect(self):
        self.window._ensure_agent_service().start()
        self.set_status('Iniciando / atualizando. O status e os modelos aparecerão aqui.')

    def pick(self):
        p=QFileDialog.getExistingDirectory(self,'Selecionar projeto',self.path.text())
        if p:self.path.setText(p)

    def save(self):
        try:
            p=Path(self.path.text().strip()).resolve(strict=True)
            if not p.is_dir():raise ValueError('A pasta de trabalho não existe.')
            if self.window._agent_service and self.window._agent_service.busy:
                raise ValueError('Aguarde o término da tarefa antes de alterar a configuração.')
            if self.mode.currentText()=='build':
                result=QMessageBox.warning(self,'MODO BUILD — OPERAÇÕES NO COMPUTADOR',
                    'Build pode editar e executar comandos. Aprovações são individuais. '
                    'Não selecione o código do NEXUS em uso para alterações automáticas. Continuar?',
                    QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if result!=QMessageBox.StandardButton.Yes:return False
            if p!=self.window._agent_workspace:
                self.window._agent_replace_workspace(str(p))
            service=self.window._ensure_agent_service()
            model=self.model.currentData();level=self.variant.currentText()
            if model and model.get('variants') and level not in model.get('variants') and level!='padrão':
                QMessageBox.information(self,'Nível de raciocínio','O modelo não anuncia '+level+'. Usando padrão.')
                level='padrão'
            service.configure(self.mode.currentText(),model,level,quick_chat=self.fast_chat.isChecked())
            self.window._agent_voice.configure(self.voice_provider.currentData(),self.voice_name.currentText(),
                                               self.tts_model.currentData())
            self.window._agent_state_lbl.setText('GPT · '+(model.get('name') if model else 'padrão')+' · '+level+
                ' · voz '+self.voice_provider.currentText())
            diag.info('agent.settings.saved',mode=self.mode.currentText(),model=(model or {}).get('id','padrão'),
                      variant=level,tts=self.voice_provider.currentData())
            from nexus.agent_preferences import save_preferences
            save_preferences(self.window._agent_workspace, self.mode.currentText(),model,level,self.fast_chat.isChecked())
            self.set_status('Configuração salva. Modelo e voz são independentes. A janela pode ser fechada.')
            return True
        except Exception as exc:
            diag.error('agent.ui.save',exc)
            QMessageBox.warning(self,'Falha ao salvar',str(exc))
            return False

    def test_voice(self):
        try:
            provider=self.voice_provider.currentData()
            self.window._agent_voice.speak('Boa noite, senhor. Teste da voz do JARVIS NEXUS.',
                provider=provider,voice=self.voice_name.currentText(),model=self.tts_model.currentData())
            self.set_status('Teste de voz solicitado. Pode consumir franquia da API escolhida.')
        except Exception as exc:QMessageBox.warning(self,'Erro',str(exc))

    def open_logs(self):
        import os
        from nexus.diagnostics import LOGS
        try:
            if os.name=='nt':os.startfile(str(LOGS))
            else:QMessageBox.information(self,'Logs',str(LOGS))
        except Exception as exc:QMessageBox.warning(self,'Logs',str(exc))

    def explain_permissions(self):
        QMessageBox.information(self,'Acesso e percepção da tela',
            'O OpenCode só conhece os arquivos e ferramentas que suas permissões permitem. '
            'Abrir este painel não concede visão contínua do monitor. Para acessar outra pasta, '
            'selecione-a como pasta de trabalho ou aprove uma permissão específica. '
            'A V1.8 permite enviar UMA captura ao GPT pelo botão do painel ou pedido explícito por voz. '
            'Não mantém compartilhamento contínuo de tela. Cada envio exige confirmação.')
