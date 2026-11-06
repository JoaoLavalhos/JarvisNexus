"""Single-display capture with local preview and explicit per-image consent."""
from __future__ import annotations
import io
import re
from nexus import diagnostics as diag

_PATTERNS=(
 r'\b(?:consegue|consegues|conseguem|pode|podes|poderia)\b.{0,22}\b(?:ver|enxergar|visualizar|olhar)\b.{0,25}\b(?:minha tela|meu monitor|a tela|na tela)\b',
 r'\b(?:est[aá]|est[aá]s|t[aá]|t[aá]s)\b.{0,15}\b(?:vendo|enxergando|visualizando)\b.{0,25}\b(?:minha tela|meu monitor|a tela|na tela)\b',
 r'\b(?:o que|que que)\b.{0,30}\b(?:voc[eê]|tu)\b.{0,20}\b(?:v[eê]|enxerga|est[aá] vendo|t[aá] vendo)\b.{0,30}\b(?:tela|monitor)\b',
 r'\b(?:olha|olhe|veja|v[eê]|analise|analisa|examine|examina|mostra|mostre)\b.{0,55}\b(?:(?:minha|a|essa|esta) tela|meu monitor|o que (?:est[aá]|tem) na tela|na tela)\b',
 r'\b(?:print|captura(?:r)?|foto|screenshot)\b.{0,30}\b(?:tela|monitor)\b',
 r'\b(?:o que)\b.{0,30}\b(?:vendo na minha tela|aparece na minha tela)\b',
)


def explicit_screen_request(text):
    text=(text or '').lower()
    if re.search(r'\b(?:n[aã]o|nunca)\s+(?:quero que\s+)?(?:veja|olhe|capture|envie|mostre|analise|ver|enxergue)\b',text):return False
    return any(re.search(p,text,re.I) for p in _PATTERNS)


def monitors():
    import mss
    with mss.mss() as capture:
        return [dict(m) for m in capture.monitors[1:]]


def capture_jpeg(monitor_index=1):
    import mss
    from PIL import Image
    with mss.mss() as capture:
        if not 1<=monitor_index<len(capture.monitors):raise ValueError('Monitor não está mais disponível.')
        shot=capture.grab(capture.monitors[monitor_index])
        image=Image.frombytes('RGB',shot.size,shot.rgb)
    image.thumbnail((1600,1000))
    out=io.BytesIO();image.save(out,format='JPEG',quality=85)
    raw=out.getvalue()
    if len(raw)>3_000_000:raise ValueError('Imagem excede 3 MB.')
    diag.info('agent.screen.captured',monitor=monitor_index,bytes=len(raw))
    return raw


def approve_capture(parent):
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtGui import QPixmap
    from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,
        QPushButton,QDialogButtonBox)
    class Preview(QDialog):
        def __init__(self):
            super().__init__(parent)
            self.image=None
            self.setWindowTitle('Prévia local — uma captura para o GPT')
            self.resize(900,650)
            layout=QVBoxLayout(self)
            info=QLabel('Confira a imagem antes de enviar ao modelo. Nenhuma imagem sai do computador até clicar em ENVIAR ESTA CAPTURA.')
            info.setWordWrap(True);layout.addWidget(info)
            bar=QHBoxLayout();self.monitor=QComboBox();bar.addWidget(self.monitor,1)
            for i,m in enumerate(monitors(),1):
                self.monitor.addItem(f"Monitor {i} · {m['width']}×{m['height']} · posição {m['left']},{m['top']}",i)
            refresh=QPushButton('ATUALIZAR CAPTURA');refresh.clicked.connect(self.capture);bar.addWidget(refresh)
            layout.addLayout(bar)
            self.preview=QLabel('Preparando prévia…');self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.preview.setMinimumSize(400,280);layout.addWidget(self.preview,1)
            self.message=QLabel();self.message.setWordWrap(True);layout.addWidget(self.message)
            buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
            self.send=buttons.addButton('ENVIAR ESTA CAPTURA',QDialogButtonBox.ButtonRole.AcceptRole)
            self.send.setEnabled(False)
            buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
            self.monitor.currentIndexChanged.connect(self.capture)
            QTimer.singleShot(0,self.capture)
        def capture(self):
            self.image=None;self.send.setEnabled(False)
            try:
                self.image=capture_jpeg(self.monitor.currentData())
                pix=QPixmap();pix.loadFromData(self.image)
                self.preview.setPixmap(pix.scaled(840,470,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
                self.message.setText(f'JPEG · {len(self.image)//1024} KB. Esta imagem exata será enviada; atualize se desejar outra captura.')
                self.send.setEnabled(True)
            except Exception as exc:
                self.preview.clear();self.message.setText('Não foi possível capturar: '+str(exc))
    dialog=Preview()
    return dialog.image if dialog.exec()==QDialog.DialogCode.Accepted else None
