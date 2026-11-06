"""Testes determinísticos das correções V1.2 — sem rede real nem chaves."""
import unittest
from unittest.mock import patch
from datetime import date, timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from nexus import activity, settings
from actions import weather_report as weather
from actions import recent_actions

class Answer:
    def __init__(self, data): self.data = data
    def raise_for_status(self): pass
    def json(self): return self.data

class Display:
    def __init__(self): self.shown=[]
    def show_content(self, title, contents): self.shown.append((title, contents))

class TestClima(unittest.TestCase):
    def setUp(self):
        self.original = settings.load
        activity.set_user_utterance("qual é a previsão amanhã?")

    def test_sem_cidade_nao_abre_browser_ou_rede(self):
        with patch.object(settings, "load", return_value={"weather_city":""}), patch.object(weather.requests, "get") as req:
            response=weather.weather_action({"day":"amanhã", "city":"São Paulo"})
        self.assertIn("status=ask",response)
        self.assertIn("cidade",response)
        req.assert_not_called()

    def test_amanha_dados_reais_no_painel(self):
        activity.set_user_utterance("Jarvis, previsão de amanhã em Canoas")
        d0=date.today().isoformat();d1=(date.today()+timedelta(days=1)).isoformat();d2=(date.today()+timedelta(days=2)).isoformat()
        geo=Answer({"results":[{"name":"Canoas","admin1":"Rio Grande do Sul","country":"Brasil","latitude":-29.9,"longitude":-51.2}]})
        forecast=Answer({"daily":{"time":[d0,d1,d2],"weather_code":[1,3,61],
            "temperature_2m_max":[31,26,23],"temperature_2m_min":[20,18,16],
            "precipitation_probability_max":[20,80,50],"precipitation_sum":[0,3.2,2]}})
        panel=Display()
        with patch.object(settings,"load", return_value={"weather_city":""}), patch.object(weather.requests, "get",side_effect=[geo,forecast]) as req:
            output=weather.weather_action({"city":"Canoas","day":"amanhã"},player=panel)
        self.assertIn("status=done", output)
        self.assertIn("26°C", output)
        self.assertIn("80%", output)
        self.assertIn(d1, output)
        self.assertIn("aba_aberta=false",output)
        self.assertTrue(panel.shown)
        self.assertEqual(req.call_count,2)
        self.assertIn('open-meteo.com',panel.shown[0][1])
        self.assertNotIn('google.com/search', output)

    def test_configured_city_when_not_said(self):
        with patch.object(settings,"load",return_value={"weather_city":"Canoas, RS"}),patch.object(weather.requests,"get",side_effect=ConnectionError("offline")):
            # Client errors result in failed; this test only checks city resolution.
            self.assertEqual(weather._choose_city('São Paulo','qual clima amanhã','Canoas, RS'),'Canoas, RS')

    def test_day_after_tomorrow(self):
        self.assertEqual(weather._day_offset("depois de amanhã")[0],2)

class TestActivity(unittest.TestCase):
    def test_record_and_read(self):
        activity.record('browser_control','status=unverified action=browser_control url=example.org')
        activity.record('weather_report','status=done action=weather_report aba_aberta=false')
        text=recent_actions.recent_actions({'limit':2})
        self.assertIn('browser_control',text)
        self.assertIn('weather_report',text)
        self.assertIn('resultado não verificado',text)

class TestLocalization(unittest.TestCase):
    def test_explicit_locale_in_prompt(self):
        prompt=(ROOT/'core'/'prompt.txt').read_text(encoding='utf-8')
        self.assertIn('PORTUGUÊS BRASILEIRO',prompt)
        self.assertIn('recent_actions',prompt)
    def test_brief_default_off(self):
        from memory.config_manager import get_brief_enabled
        from unittest.mock import patch
        with patch('memory.config_manager.load_api_keys',return_value={}):
            self.assertFalse(get_brief_enabled())

if __name__ == '__main__': unittest.main()
