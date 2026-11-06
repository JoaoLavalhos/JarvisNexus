"""V19 regression tests: conversation history, permissions and target detection."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from nexus.agent_permissions import DEFAULT_RULES,validate_rules
from nexus.agent_verification import is_html_edit_request, requested_lines, looks_like_chocolate_catalog, file_instruction
from nexus import conversation_log as activity

class V19Regression(unittest.TestCase):
    def test_form_and_edit_without_repeated_permission(self):
        self.assertIn({'action':'edit','resource':'*','effect':'allow'},DEFAULT_RULES)
        self.assertIn({'action':'external_directory','resource':'*','effect':'ask'},DEFAULT_RULES)
        self.assertIn({'action':'shell','resource':'*','effect':'ask'},DEFAULT_RULES)
        self.assertNotIn({'action':'shell','resource':'*','effect':'allow'},DEFAULT_RULES)
        self.assertTrue(validate_rules(DEFAULT_RULES))

    def test_website_request_without_html_word_selects_target(self):
        for prompt in ('Faça do mesmo arquivo longo um site profissional de mil linhas',
                       'Transforme a página em uma loja com 1000 linhas',
                       'Altere o HTML para mil linhas'):
            self.assertTrue(is_html_edit_request(prompt))
            self.assertEqual(requested_lines(prompt),1000)

    def test_catalog_detected_from_selected_html_not_just_prompt(self):
        with tempfile.TemporaryDirectory() as td:
            page=Path(td)/'longo.html'
            page.write_text('<html><title>Cacau Show</title><body>Trufa de chocolate</body></html>',encoding='utf-8')
            text='Faça do mesmo arquivo longo um site profissional de mil linhas'
            self.assertTrue(looks_like_chocolate_catalog(text,page))
            self.assertIn('OTIMIZAÇÃO DISPONÍVEL',file_instruction(text,page))
            other=Path(td)/'site.html';other.write_text('<html><title>Consultório</title></html>',encoding='utf-8')
            self.assertFalse(looks_like_chocolate_catalog(text,other))

    def test_complete_conversation_and_duplicate_filter(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'Activity.log'
            with patch.object(activity,'PATH',path),patch.dict(os.environ,{'NEXUS_ACTIVITY_LOG':'1'}):
                activity._LAST.update(speaker='',text='',time=0)
                self.assertTrue(activity.capture_ui_line('VOCÊ (Groq 0.50s): Quero editar o site'))
                self.assertFalse(activity.capture_ui_line('VOCÊ (Groq→GPT): Quero editar o site'))
                self.assertTrue(activity.record('GPT','Edição feita.\nLinha seguinte.'))
                text=path.read_text(encoding='utf-8')
                self.assertEqual(text.count('Quero editar o site'),1)
                self.assertIn('Linha seguinte.',text)
                self.assertFalse(activity.capture_ui_line('SYS: API key fake'))
            with patch.object(activity,'PATH',path),patch.dict(os.environ,{'NEXUS_ACTIVITY_LOG':'0'}):
                self.assertFalse(activity.record('VOCÊ','Privado'))
                self.assertNotIn('Privado',path.read_text(encoding='utf-8'))

    def test_ui_never_switches_execution_tab_automatically(self):
        src=(Path(__file__).resolve().parent.parent/'ui.py').read_text(encoding='utf-8')
        segment=src.split('def _agent_submit_on_ui(',1)[1].split('def _agent_stop_all_on_ui(',1)[0]
        self.assertNotIn('self._open_agent_execution()',segment)
        segment=src.split('def _agent_event_on_ui(',1)[1].split('def _agent_cancel_on_ui(',1)[0]
        self.assertNotIn('self._open_agent_execution()',segment)

if __name__=='__main__': unittest.main()
