"""Native OpenCode question forms. No automatic answers or external navigation."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QLabel,QScrollArea,QWidget,QComboBox,
    QLineEdit,QListWidget,QListWidgetItem,QDialogButtonBox)


def ask_form(parent,form):
    dialog=QDialog(parent);dialog.setWindowTitle('O agente aguarda sua resposta')
    dialog.resize(660,480);layout=QVBoxLayout(dialog)
    title=QLabel(str(form.get('title') or 'Pergunta do agente'));title.setTextFormat(Qt.TextFormat.PlainText);title.setWordWrap(True);layout.addWidget(title)
    area=QScrollArea();area.setWidgetResizable(True);body=QWidget();fields_layout=QVBoxLayout(body);area.setWidget(body);layout.addWidget(area,1)
    controls={}
    for field in form.get('fields',[]):
        key=field.get('key');kind=field.get('type')
        if not key:continue
        if field.get('hidden'):
            if 'default' in field:controls[key]=(field,None)
            continue
        label=QLabel(str(field.get('title') or key));label.setTextFormat(Qt.TextFormat.PlainText);label.setWordWrap(True);fields_layout.addWidget(label)
        if field.get('description'):
            description=QLabel(str(field['description']));description.setTextFormat(Qt.TextFormat.PlainText);description.setWordWrap(True);fields_layout.addWidget(description)
        options=field.get('options') or []
        if kind=='multiselect':
            control=QListWidget()
            for option in options:
                value=option.get('value') if isinstance(option,dict) else str(option)
                item=QListWidgetItem(str(option.get('label',value) if isinstance(option,dict) else option))
                item.setData(Qt.ItemDataRole.UserRole,value);item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if value in field.get('default',[]) else Qt.CheckState.Unchecked);control.addItem(item)
        elif options or kind=='boolean':
            control=QComboBox();control.addItem('Escolha uma resposta…',None)
            entries=[{'label':'Sim','value':True},{'label':'Não','value':False}] if kind=='boolean' else options
            for option in entries:
                value=option.get('value') if isinstance(option,dict) else str(option)
                control.addItem(str(option.get('label',value) if isinstance(option,dict) else option),value)
            if 'default' in field:control.setCurrentIndex(max(0,control.findData(field['default'])))
            if field.get('custom') and kind=='string':control.setEditable(True)
        else:
            control=QLineEdit(str(field.get('default','')));control.setPlaceholderText(str(field.get('placeholder') or ''))
            if kind=='external':
                info=QLabel('Referência externa (não aberta automaticamente): '+str(field.get('url','')))
                info.setTextFormat(Qt.TextFormat.PlainText);info.setWordWrap(True);fields_layout.addWidget(info)
        control.setObjectName('FormField_'+str(key));fields_layout.addWidget(control);controls[key]=(field,control)
    error=QLabel();error.setWordWrap(True);layout.addWidget(error)
    buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText('ENVIAR RESPOSTA')
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('CANCELAR TAREFA')
    layout.addWidget(buttons);answer={}
    def submit():
        try:
            answer.clear()
            for key,(field,control) in controls.items():
                kind=field.get('type')
                if control is None:value=field['default']
                elif isinstance(control,QListWidget):value=[control.item(i).data(Qt.ItemDataRole.UserRole) for i in range(control.count()) if control.item(i).checkState()==Qt.CheckState.Checked]
                elif isinstance(control,QComboBox):
                    value=control.currentData()
                    if control.isEditable() and control.currentText()!=control.itemText(control.currentIndex()):value=control.currentText()
                else:
                    value=control.text().strip()
                    if value and kind in ('integer','number'):value=int(value) if kind=='integer' else float(value)
                if field.get('required') and (value is None or value=='' or value==[]):raise ValueError('Responda: '+str(field.get('title') or key))
                if value is not None:answer[key]=value
            dialog.accept()
        except (ValueError,TypeError) as exc:error.setText(str(exc))
    buttons.accepted.connect(submit);buttons.rejected.connect(dialog.reject)
    return dict(answer) if dialog.exec()==QDialog.DialogCode.Accepted else None
