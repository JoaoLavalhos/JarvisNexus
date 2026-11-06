"""Standalone visual test — doesn't use microphone, keys, Gemini or Groq.

The animated level here is SIMULATED for preview only. Real NEXUS audio
reactions are driven by the unchanged Mark-LVI live HUD.
"""
from __future__ import annotations
import sys
from PyQt6.QtWidgets import (QApplication,QVBoxLayout,QWidget,QLabel,QComboBox,QPushButton,QHBoxLayout)
from PyQt6.QtCore import Qt
from nexus import settings
from nexus.studio import CorePreview, NexusStudio


def main():
    app=QApplication(sys.argv)
    w=QWidget()
    w.setWindowTitle('JARVIS NEXUS — Visual Preview (sem APIs)')
    w.setStyleSheet('background:#050d18;color:#dfeafc;font:11pt "Segoe UI";')
    w.resize(700,560)
    lay=QVBoxLayout(w);lay.setSpacing(9);lay.setContentsMargins(22,18,22,20)
    title=QLabel('JARVIS NEXUS  /  CORE VISUAL LAB')
    title.setStyleSheet('color:#00d5ff;font-size:18pt;font-weight:700;')
    lay.addWidget(title)
    note=QLabel('Prévia animada: nível de áudio SIMULADO, sem conexão externa.')
    note.setStyleSheet('color:#8caec7;')
    lay.addWidget(note)
    preview=CorePreview();lay.addWidget(preview,1)
    bar=QHBoxLayout()
    combo=QComboBox()
    for style in settings.STYLES:
        combo.addItem(settings.STYLE_LABELS[style],style)
    combo.setCurrentIndex(settings.STYLES.index(settings.load()['style']))
    combo.currentIndexChanged.connect(lambda _:setattr(preview,'style_id',combo.currentData()))
    bar.addWidget(combo)
    def launch():
        studio=NexusStudio(parent=w)
        studio.updated.connect(lambda: (setattr(preview,'accent',settings.load()['accent']),
                                         setattr(preview,'style_id',settings.load()['style'])))
        studio.exec()
    btn=QPushButton('NEXUS STUDIO');btn.clicked.connect(launch);bar.addWidget(btn)
    lay.addLayout(bar)
    preview.style_id=combo.currentData()
    w.show();return app.exec()


if __name__=='__main__':raise SystemExit(main())
