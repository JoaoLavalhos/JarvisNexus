"""Non-modal execution dock, independent of settings and the assistant voice."""
from datetime import datetime
import json
from PyQt6.QtCore import Qt,QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTabWidget,
    QPlainTextEdit,QTreeWidget,QTreeWidgetItem,QHeaderView)
from nexus import diagnostics as diag

STYLE='''QWidget{background:#071724;color:#d7f4ff;font:10pt "Segoe UI";}
QTreeWidget,QPlainTextEdit{background:#0b2030;color:#e0f7ff;border:1px solid #28566e;}
QHeaderView::section{background:#183c51;color:#ccefff;padding:5px;border:none;}
QPushButton{background:#17445a;color:#e8f8ff;border:1px solid #40839c;padding:6px;border-radius:4px;}
QTabBar::tab{background:#102b40;color:#b9d9e5;padding:6px;}QTabBar::tab:selected{background:#20566c;color:white;}
'''

class AgentExecutionPanel(QWidget):
    def __init__(self, window):
        super().__init__(window);self.window=window;self.rows={};self.seen=set();self.messages=[]
        self.setStyleSheet(STYLE)
        root=QVBoxLayout(self);root.setContentsMargins(8,6,8,6)
        bar=QHBoxLayout();self.status=QLabel('Pronto. Ferramentas e mensagens aparecerão aqui.');self.status.setWordWrap(True);bar.addWidget(self.status,1)
        stop=QPushButton('PARAR TAREFA');stop.clicked.connect(window._agent_stop_all_on_ui);bar.addWidget(stop)
        settings=QPushButton('MODELO / PASTA');settings.clicked.connect(window._open_agent_dialog);bar.addWidget(settings)
        root.addLayout(bar)
        self.tabs=QTabWidget();root.addWidget(self.tabs,1)
        activity=QWidget();layout=QVBoxLayout(activity);layout.setContentsMargins(0,0,0,0)
        self.tree=QTreeWidget();self.tree.setHeaderLabels(['Hora','Etapa / ferramenta','Comando ou resultado','Duração'])
        self.tree.setRootIsDecorated(False);self.tree.setColumnWidth(0,75);self.tree.setColumnWidth(1,240)
        self.tree.header().setStretchLastSection(False);self.tree.header().setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(3,QHeaderView.ResizeMode.ResizeToContents)
        self.tree.currentItemChanged.connect(self._select);layout.addWidget(self.tree,1)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.details.setMaximumHeight(140)
        self.details.setPlaceholderText('Selecione uma etapa para ver argumentos, comando, saída ou erro.');layout.addWidget(self.details)
        self.tabs.addTab(activity,'EXECUÇÃO')
        self.public=QPlainTextEdit();self.public.setReadOnly(True);self.public.setPlaceholderText('Mensagens públicas do agente durante a tarefa. O raciocínio interno não é exibido.')
        self.tabs.addTab(self.public,'MENSAGENS DO AGENTE')
        self.changes=QPlainTextEdit();self.changes.setReadOnly(True);self.changes.setPlaceholderText('Diffs e verificações locais dos arquivos.');self.tabs.addTab(self.changes,'ARQUIVOS / VERIFICAÇÃO')
        self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(500)

    def begin(self):
        self.rows.clear();self.seen.clear();self.messages.clear();self.tree.clear();self.public.clear();self.changes.clear();self.details.clear()
        self.status.setText('Pedido recebido. Aguardando o agente…')

    def append(self,item):
        if not isinstance(item,dict):return
        event_id=item.get('event_id')
        if event_id and event_id in self.seen:return
        if event_id:self.seen.add(event_id)
        et=item.get('type','');key=item.get('tool_id') if item.get('tool') else None
        if et=='nexus.commentary':
            text=item.get('detail','')
            if text and (not self.messages or self.messages[-1]!=text):
                self.messages.append(text);self.messages=self.messages[-60:];self.public.setPlainText('\n\n'.join(self.messages))
        if et in ('nexus.diff','nexus.verification'):
            self.changes.appendPlainText(item.get('diff') or item.get('detail') or '')
        row=self.rows.get(key) if key else None
        if row is None:
            row=QTreeWidgetItem();self.tree.addTopLevelItem(row)
            if key:self.rows[key]=row
        else:
            previous=row.data(0,Qt.ItemDataRole.UserRole) or {}
            item={**previous,**item,'arguments':item.get('arguments') or previous.get('arguments','')}
        timestamp=datetime.fromtimestamp(item.get('ts',0)).strftime('%H:%M:%S')
        duration=f"{item['duration']}s" if item.get('duration') is not None else '—'
        text=diag.sanitize(item.get('detail') or item.get('arguments') or item.get('output') or '')
        for col,value in enumerate([timestamp,item.get('label',et),text[:260],duration]):row.setText(col,str(value))
        row.setData(0,Qt.ItemDataRole.UserRole,item)
        row.setToolTip(2,text[:4000])
        if item.get('failure'):row.setForeground(1,QColor('#ff948b'))
        elif et=='session.tool.success':row.setForeground(1,QColor('#6ee4b4'))
        if self.tree.currentItem() is row:self._select(row,None)
        self.tree.scrollToItem(row)
        while self.tree.topLevelItemCount()>450:
            old=self.tree.takeTopLevelItem(0)
            self.rows={k:v for k,v in self.rows.items() if v is not old}

    def _select(self,row,_):
        if row:self.details.setPlainText(json.dumps(row.data(0,Qt.ItemDataRole.UserRole) or {},ensure_ascii=False,indent=2))

    def tick(self):
        service=self.window._agent_service
        if not service:return
        if service.busy:self.status.setText(service.progress.description())
        else:
            state=service.task_state.snapshot()
            labels={'succeeded':'Concluído','failed':'Falhou','cancelled':'Cancelado','recovery_required':'Interrupção não confirmada'}
            self.status.setText(labels.get(state.get('phase'),'Pronto')+(' · '+state['detail'][:250] if state.get('detail') else ''))
