"""NEXUS Studio: real, functional controls for the live HUD and existing tools.

Dedicated visual configuration is never mixed with API credentials. No additional
privileged actions are introduced here; buttons delegate to existing Mark-LVI UI.
"""
from __future__ import annotations

import time
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter, QFont, QColor
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QVBoxLayout, QWidget,
    QLabel, QPushButton, QComboBox, QTabWidget, QSlider,
    QCheckBox, QGridLayout, QScrollArea, QLineEdit, QTextEdit,
)

from nexus import settings
from nexus.cores import draw

DARK = "#050d18"
PANEL = "#0b1729"
ACC = "#00d5ff"
MUTED = "#91a8c6"


class CorePreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(290, 290)
        self.style_id = "reactor"
        self.accent = settings.DEFAULT["accent"]
        self.intensity = 80
        self.particles = True
        self.reduced_motion = False
        self._origin = time.monotonic()
        self._avatar = None
        self._avatar_time = self._origin
        try:
            from core.avatar import HoloAvatar
            self._avatar = HoloAvatar()
        except Exception:
            pass
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(33)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(DARK))
        w,h = self.width(),self.height()
        cx,cy=w/2,h/2
        radius=min(w,h)*.43
        try:
            elapsed = time.monotonic()-self._origin
            level=.35+.2*__import__('math').sin(elapsed*2)
            if self.style_id == "face" and self._avatar is not None:
                dt=max(0.001,min(.09,time.monotonic()-self._avatar_time))
                self._avatar_time=time.monotonic()
                self._avatar.step(dt,level,state="LISTENING")
                self._avatar.paint(p,cx,cy,radius*.43,
                    QColor(self.accent),QColor("#e5fcff"),QColor(DARK))
            else:
                draw(p,self.style_id,cx,cy,radius,elapsed,level,
                     "LISTENING", {"accent":self.accent,"secondary":"#f1feff"},
                     {"intensity":self.intensity,"particles":self.particles,
                      "reduced_motion":self.reduced_motion})
        finally:
            p.end()


class NexusStudio(QDialog):
    updated = pyqtSignal()

    def __init__(self, *, parent=None, audio=None, providers=None,
                 memory=None, microphone=None, interrupt=None, ptt=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("NEXUS STUDIO V1.2 | Centro de comando")
        self.resize(820, 560)
        self.setMinimumSize(660,480)
        self.setStyleSheet(f"""
        QDialog {{background:{DARK};color:#e7f6ff;font:10pt 'Segoe UI';}}
        QLabel {{color:#dceaf5;}}
        QTabWidget::pane {{border:1px solid #233e5c;background:{PANEL};border-radius:8px;}}
        QTabBar::tab {{background:#091528;color:#9ab1c9;padding:10px 19px;
                       border:1px solid #19304b;}}
        QTabBar::tab:selected {{color:{ACC};background:#10253a;border-bottom:2px solid {ACC};}}
        QPushButton {{background:#10233a;color:#c6eafa;border:1px solid #2b536f;
                      border-radius:7px;padding:9px 13px;font-weight:600;}}
        QPushButton:hover {{background:#193954;border-color:{ACC};color:white;}}
        QPushButton:pressed {{background:#075375;}}
        QComboBox {{background:#0c2035;color:white;padding:8px;border:1px solid #2c5473;
                    border-radius:6px;}}
        QComboBox QAbstractItemView {{background:#122438;color:white;selection-background-color:#225a75;}}
        QCheckBox {{color:#dbeafa;spacing:12px;}}
        QSlider::groove:horizontal {{background:#17334b;height:7px;border-radius:3px;}}
        QSlider::handle:horizontal {{background:{ACC};width:17px;margin:-5px 0;border-radius:8px;}}
        """)
        self._callbacks = {
            "audio": audio, "providers":providers, "memory":memory,
            "microphone":microphone,"interrupt":interrupt,"ptt":ptt,
            "activity": self._show_recent_actions,
        }
        self.data=settings.load()
        outer=QVBoxLayout(self);outer.setContentsMargins(24,20,24,18);outer.setSpacing(14)
        header=QHBoxLayout()
        heading=QLabel("N E X U S    S T U D I O")
        heading.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        heading.setStyleSheet(f"color:{ACC};")
        header.addWidget(heading)
        header.addStretch()
        tag=QLabel("V1.2   /   CONTROLES & VISUAL")
        tag.setStyleSheet("color:#86aac2;letter-spacing:2px;")
        header.addWidget(tag)
        outer.addLayout(header)
        tabs=QTabWidget();outer.addWidget(tabs,1)
        visual=QWidget();tabs.addTab(visual,"Núcleos e efeitos")
        audio_tab=QWidget();tabs.addTab(audio_tab,"Áudio e IA")
        ops=QWidget();tabs.addTab(ops,"Controles")
        self._make_visual(visual)
        self._make_audio(audio_tab)
        self._make_ops(ops)
        bottom=QHBoxLayout()
        desc=QLabel("Alterações visuais aplicadas em tempo real e salvas no projeto")
        desc.setStyleSheet("color:#7898b3;font-size:9pt;")
        bottom.addWidget(desc)
        bottom.addStretch()
        close=QPushButton("FECHAR");close.clicked.connect(self.close);bottom.addWidget(close)
        outer.addLayout(bottom)

    @staticmethod
    def _section(parent, title):
        label=QLabel(title)
        label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        label.setStyleSheet(f"color:{ACC};margin:0 0 8px 0;")
        parent.addWidget(label)

    def _make_visual(self, widget):
        row=QHBoxLayout(widget);row.setContentsMargins(22,20,22,18);row.setSpacing(20)
        side=QVBoxLayout();side.setSpacing(11);row.addLayout(side,3)
        self._section(side,"ESCOLHA O NÚCLEO")
        self.style=QComboBox()
        for id in settings.STYLES:
            self.style.addItem(settings.STYLE_LABELS[id],id)
        self.style.setCurrentIndex(settings.STYLES.index(self.data["style"]))
        self.style.currentIndexChanged.connect(self._changed)
        side.addWidget(self.style)
        self._section(side,"COR DA INTERFACE")
        colors=QGridLayout();colors.setSpacing(7)
        for i,(name,color) in enumerate(settings.PRESETS.items()):
            b=QPushButton(name)
            b.setMinimumHeight(32)
            b.setStyleSheet(f"QPushButton{{background:#111c2a;color:{color};border:1px solid {color};border-radius:6px;}}"
                            f"QPushButton:hover{{background:{color};color:#08121e;}}")
            b.clicked.connect(lambda _c=False, c=color:self._choose_color(c))
            colors.addWidget(b,i//3,i%3)
        side.addLayout(colors)
        self._section(side,"INTENSIDADE DE REAÇÃO À VOZ")
        intensityrow=QHBoxLayout()
        self.intensity=QSlider(Qt.Orientation.Horizontal)
        self.intensity.setRange(10,100);self.intensity.setValue(self.data["intensity"])
        self.intensity.valueChanged.connect(self._changed)
        self.intval=QLabel(str(self.data["intensity"])+"%")
        self.intval.setMinimumWidth(48)
        intensityrow.addWidget(self.intensity);intensityrow.addWidget(self.intval)
        side.addLayout(intensityrow)
        self.particles=QCheckBox("Partículas dinâmicas")
        self.particles.setChecked(self.data["particles"])
        self.particles.stateChanged.connect(self._changed);side.addWidget(self.particles)
        self.grid=QCheckBox("Grade de referência no fundo")
        self.grid.setChecked(self.data["grid"])
        self.grid.stateChanged.connect(self._changed);side.addWidget(self.grid)
        self.reduced=QCheckBox("Movimento reduzido (economia de CPU)")
        self.reduced.setChecked(self.data["reduced_motion"])
        self.reduced.stateChanged.connect(self._changed);side.addWidget(self.reduced)
        self.performance=QCheckBox("Priorizar respostas rápidas (recomendado)")
        self.performance.setChecked(self.data.get("performance_mode", True))
        self.performance.setToolTip("Reduz o custo das animações enquanto o assistente está pensando; não modifica a voz.")
        self.performance.stateChanged.connect(self._changed);side.addWidget(self.performance)
        side.addStretch()
        self.preview=CorePreview();row.addWidget(self.preview,4)
        self._update_preview()

    def _choose_color(self, color):
        self.data["accent"]=color
        self._changed()

    def _update_preview(self):
        if hasattr(self,"preview"):
            self.preview.style_id=self.data["style"]
            self.preview.accent=self.data["accent"]
            self.preview.intensity=self.data["intensity"]
            self.preview.particles=self.data["particles"]
            self.preview.reduced_motion=self.data["reduced_motion"]
            self.preview.update()

    def _changed(self,*_):
        self.data=settings.save(style=self.style.currentData(),
            accent=self.data["accent"],intensity=self.intensity.value(),
            particles=self.particles.isChecked(),grid=self.grid.isChecked(),
            reduced_motion=self.reduced.isChecked(),
            performance_mode=self.performance.isChecked())
        self.intval.setText(str(self.data["intensity"])+"%")
        self._update_preview()
        self.updated.emit()

    def _button(self,parent,label,which):
        btn=QPushButton(label)
        callback=self._callbacks.get(which)
        if callback:
            if which == "activity":
                # Este diálogo pertence ao Studio: mantenha o pai aberto.
                # _call() fecha o Studio e WA_DeleteOnClose apagaria o widget.
                btn.clicked.connect(self._show_recent_actions)
            else:
                btn.clicked.connect(lambda _checked=False,cb=callback:self._call(cb))
        else:btn.setEnabled(False)
        parent.addWidget(btn)

    def _call(self,cb):
        self.close()  # close dialog before parent popup/control may open
        cb()

    def _make_audio(self,widget):
        layout=QVBoxLayout(widget);layout.setContentsMargins(28,26,28,22);layout.setSpacing(13)
        self._section(layout,"CONEXÃO DE VOZ")
        for line in (
            "Reconhecimento  •  Groq Whisper Large V3 / Ctrl + Espaço",
            "Conversação      •  Gemini Live (preservado)",
            "Saída de voz     •  Gemini Live (Fish Audio em fase futura)",
            "Suas chaves não são exibidas neste painel.",
        ):
            l=QLabel(line);l.setWordWrap(True);l.setStyleSheet("color:#bbcee1;");layout.addWidget(l)
        layout.addSpacing(12)
        self._button(layout,"CONFIGURAR MICROFONE E ALTO-FALANTES","audio")
        self._button(layout,"CONFIGURAR MOTOR DE IA / PROVEDORES","providers")
        note=QLabel("O modo Groq usa gravação manual para evitar cortes de frases. "
                    "Segure Ctrl+Espaço, fale e solte para transcrever.")
        note.setWordWrap(True);note.setStyleSheet("color:#7aa2bc;margin-top:10px;")
        layout.addWidget(note);layout.addStretch()

    def _show_recent_actions(self):
        from nexus import activity
        popup = QDialog(self)
        popup.setWindowTitle("NEXUS V1.2 | Ações desta sessão")
        popup.resize(700, 420)
        popup.setStyleSheet(self.styleSheet())
        layout = QVBoxLayout(popup)
        info = QLabel("Histórico temporário de ferramentas. Fechar o programa limpa este registro.")
        info.setWordWrap(True)
        layout.addWidget(info)
        results = QTextEdit(popup)
        results.setReadOnly(True)
        results.setPlainText(activity.describe(30))
        results.setStyleSheet("background:#071426;color:#d8ecfa;border:1px solid #26506b;padding:9px;")
        layout.addWidget(results)
        close = QPushButton("FECHAR")
        close.clicked.connect(popup.accept)
        layout.addWidget(close)
        popup.exec()

    def _save_city(self):
        city = self.city_input.text().strip()
        settings.save(weather_city=city)
        self.updated.emit()
        self.city_input.setToolTip(f"Cidade padrão: {city or '(não definida)'} — salva")

    def _make_ops(self,widget):
        layout=QVBoxLayout(widget);layout.setContentsMargins(28,26,28,22);layout.setSpacing(11)
        self._section(layout,"FERRAMENTAS E SISTEMA")
        self._button(layout,"CONSULTAR HISTÓRICO DE AÇÕES","activity")
        self._button(layout,"ABRIR MEMÓRIA PERSISTENTE","memory")
        self._button(layout,"LIGAR / DESLIGAR MICROFONE","microphone")
        self._button(layout,"ATIVAR / DESATIVAR PUSH-TO-TALK","ptt")
        self._button(layout,"INTERROMPER RESPOSTA ATUAL","interrupt")
        layout.addSpacing(10)
        self._section(layout, "LOCALIZAÇÃO OPCIONAL PARA PREVISÃO DO TEMPO")
        cityrow = QHBoxLayout()
        self.city_input = QLineEdit()
        self.city_input.setPlaceholderText("Ex.: Canoas, RS (vazio = perguntar a cidade)")
        self.city_input.setText(self.data.get("weather_city", ""))
        self.city_input.setStyleSheet("background:#0c2035;color:white;padding:8px;border:1px solid #2c5473;border-radius:6px;")
        self.city_input.setMaximumWidth(420)
        cityrow.addWidget(self.city_input)
        save_city = QPushButton("SALVAR CIDADE")
        save_city.clicked.connect(self._save_city)
        cityrow.addWidget(save_city)
        layout.addLayout(cityrow)
        note_city = QLabel("A cidade só é usada para consultas solicitadas. Sem acesso à localização automática.")
        note_city.setWordWrap(True)
        layout.addWidget(note_city)
        from memory.config_manager import get_brief_enabled, save_brief_enabled
        brief_check = QCheckBox("Ler notícias automaticamente quando iniciar")
        brief_check.setChecked(get_brief_enabled())
        brief_check.toggled.connect(save_brief_enabled)
        layout.addWidget(brief_check)
        layout.addSpacing(10)
        self._section(layout,"PRIVACIDADE / REDE")
        remote=QCheckBox("Habilitar controle pelo celular (abre portas de rede no próximo início)")
        remote.setChecked(self.data.get("remote_enabled",False))
        remote.toggled.connect(lambda checked: (settings.save(remote_enabled=checked), self.updated.emit()))
        layout.addWidget(remote)
        notice=QLabel("Desativado por padrão. Ao mudar esta opção, reinicie o aplicativo para aplicar.")
        notice.setStyleSheet("color:#96a7bd;font-size:9pt;")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        layout.addSpacing(10)
        self._section(layout,"ATALHOS")
        for line in ("Ctrl + Espaço    •    Capturar fala com Groq", "F4                 •    Silenciar microfone",
                     "Esc                •    Interromper", "F11                •    Tela cheia"):
            label=QLabel(line);label.setStyleSheet("color:#a5bed1;");layout.addWidget(label)
        layout.addStretch()
