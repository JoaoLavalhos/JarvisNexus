"""Previsão de verdade no painel; jamais abre navegador por conta própria.

Fonte: Open-Meteo (CC BY 4.0). Sem credenciais. Sem previsão inventada.
"""
from __future__ import annotations

from datetime import date, timedelta, datetime
import re
import unicodedata

import requests
from core import outcome
from nexus import activity, settings

GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"

WEATHER_CODES = {
    0: "céu limpo", 1: "predominantemente limpo", 2: "parcialmente nublado",
    3: "nublado", 45: "neblina", 48: "neblina com geada",
    51: "garoa leve", 53: "garoa moderada", 55: "garoa forte",
    56: "garoa congelante leve", 57: "garoa congelante forte",
    61: "chuva fraca", 63: "chuva moderada", 65: "chuva forte",
    66: "chuva congelante leve", 67: "chuva congelante forte",
    71: "neve fraca", 73: "neve moderada", 75: "neve forte", 77: "grãos de neve",
    80: "pancadas de chuva fracas", 81: "pancadas de chuva moderadas", 82: "pancadas de chuva fortes",
    85: "pancadas de neve fracas", 86: "pancadas de neve fortes",
    95: "trovoadas", 96: "trovoadas com granizo", 99: "trovoadas com granizo forte",
}


def _normalized(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", t.casefold())
                   if not unicodedata.combining(c)).strip()


def _day_offset(raw: str, utterance: str = "") -> tuple[int | None, str]:
    q = _normalized(raw or "")
    spoken = _normalized(utterance or "")
    if not q:
        q = spoken
    if any(x in q for x in ("depois de amanha", "day after tomorrow")):
        return 2, "depois de amanhã"
    if "amanha" in q or "tomorrow" in q:
        return 1, "amanhã"
    if "hoje" in q or "today" in q or not q:
        return 0, "hoje"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", q):
        try:
            d = date.fromisoformat(q)
            diff = (d - date.today()).days
            return (diff, d.strftime("%d/%m/%Y")) if 0 <= diff <= 15 else (None, "")
        except ValueError:
            return None, ""
    # Frase livre pode incluir 'previsão para amanhã' — a busca acima cobriu.
    return None, ""


def _choose_city(raw_city: str, utterance: str, saved_city: str) -> str:
    raw_city = (raw_city or "").strip()
    saved_city = (saved_city or "").strip()
    if not raw_city:
        return saved_city
    if not utterance:
        # Sem evidência da frase do usuário, não confie em uma cidade que o modelo inventou.
        return saved_city
    norm_utt = _normalized(utterance)
    norm_city = _normalized(raw_city)
    short_city = norm_city.split(",")[0].strip()
    if short_city and short_city in norm_utt:
        return raw_city
    # Ex.: a pessoa perguntou 'amanhã' e o modelo fabricou 'São Paulo'.
    return saved_city


def _num(v, unit="") -> str:
    try:
        return f"{float(v):.0f}{unit}" if v is not None else "não informado"
    except (ValueError, TypeError):
        return "não informado"


def weather_action(parameters: dict, player=None, session_memory=None) -> str:
    """Retorna previsão observada. Não abre abas e não escolhe cidade presumida."""
    prefs = settings.load()
    utterance = activity.last_user_utterance()
    city = _choose_city(str(parameters.get("city") or ""), utterance,
                        prefs.get("weather_city", ""))
    if not city:
        return outcome.ask("weather_report", "Para qual cidade o senhor deseja a previsão?")
    raw_day = str(parameters.get("day") or parameters.get("time") or "")
    offset, label = _day_offset(raw_day, utterance)
    if offset is None:
        return outcome.ask("weather_report", "Deseja a previsão para hoje, amanhã ou uma data específica até 15 dias?")
    # Verifica o dia solicitado no texto quando o modelo manda valor inconsistente.
    mentioned_offset, _ = _day_offset("", utterance)
    if utterance and ("amanha" in _normalized(utterance) or "tomorrow" in _normalized(utterance)):
        if mentioned_offset is not None:
            offset = mentioned_offset
            label = "amanhã" if offset == 1 else "depois de amanhã"
    try:
        response = requests.get(GEOCODE, params={"name": city, "count": 8,
                               "language": "pt", "format": "json"}, timeout=(4, 8))
        response.raise_for_status()
        cities = response.json().get("results") or []
        if not cities:
            return outcome.ask("weather_report", f"Não encontrei a cidade '{city}'. Informe cidade e estado.")
        norm_target = _normalized(city.split(",")[0])
        exact = [r for r in cities if _normalized(r.get("name", "")) == norm_target]
        candidates = exact or cities
        states = {(c.get("name"), c.get("admin1"), c.get("country")) for c in candidates}
        # Em nomes duplicados, não suponha o estado.
        if len(states) > 1 and len(exact) > 1 and "," not in city:
            desc = "; ".join(f"{x[0]}/{x[1]}, {x[2]}" for x in sorted(states, key=lambda t:str(t))[:4])
            return outcome.ask("weather_report", f"Há mais de uma cidade com esse nome: {desc}. Informe o estado.")
        loc = candidates[0]
        response = requests.get(FORECAST, params={
            "latitude": loc["latitude"], "longitude": loc["longitude"],
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum",
            "timezone": "auto", "forecast_days": max(3, offset+1),
        }, timeout=(4, 10))
        response.raise_for_status()
        data = response.json().get("daily") or {}
        dates = data.get("time") or []
        if len(dates) <= offset:
            return outcome.failed("weather_report", "A API não retornou a data desejada.")
        def pick(field):
            values = data.get(field) or []
            return values[offset] if len(values) > offset else None
        place = ", ".join(x for x in (loc.get("name"), loc.get("admin1")) if x)
        cond = WEATHER_CODES.get(pick("weather_code"), "condição não informada")
        high = _num(pick("temperature_2m_max"), "°C")
        low = _num(pick("temperature_2m_min"), "°C")
        chance = _num(pick("precipitation_probability_max"), "%")
        rain = _num(pick("precipitation_sum"), " mm")
        report = (f"PREVISÃO PARA {label.upper()} — {place}\n"
                  f"Data: {dates[offset]}\n"
                  f"Condição: {cond}\n"
                  f"Mínima: {low} | Máxima: {high}\n"
                  f"Probabilidade máxima de chuva: {chance}\n"
                  f"Precipitação estimada: {rain}\n"
                  f"Fonte: Open-Meteo (CC BY 4.0), consultado às {datetime.now().strftime('%H:%M')}\n"
                  f"https://open-meteo.com/")
        display_sent = False
        if player is not None:
            try:
                player.show_content(f"CLIMA · {place} · {label}", report)
                display_sent = True
            except Exception:
                pass
        return (outcome.done("weather_report", cidade=place, dia=dates[offset],
                             condicao=cond, minima=low, maxima=high, chuva=chance,
                             aba_aberta=False, envio_ao_painel=display_sent, fonte="Open-Meteo")
                + " | " + report.replace("\n", "; "))
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        return outcome.failed("weather_report", f"Não foi possível consultar a previsão: {type(exc).__name__}. Nenhuma aba foi aberta.")


TOOL = {
    "name": "weather_report",
    "description": (
        "Consultar previsão meteorológica REAL, GRATUITA, sem abrir navegador, e exibir no painel. "
        "Use para clima/temperatura/chuva de hoje, amanhã ou data. "
        "CIDADE: forneça APENAS a que o usuário mencionou explicitamente. "
        "Se não mencionou, deixe city vazio: o aplicativo usa a cidade escolhida "
        "nas configurações ou pergunta a cidade. NUNCA invente São Paulo ou outra cidade. "
        "Aguarde retorno e baseie a resposta somente nos dados retornados."
    ),
    "parameters": {"type": "OBJECT", "properties": {
        "city": {"type": "STRING", "description": "Cidade citada pelo usuário, ou vazio. NÃO adivinhe localização."},
        "day": {"type": "STRING", "description": "hoje | amanhã | depois de amanhã | data YYYY-MM-DD"},
    }, "required": []},
    "handler": weather_action,
}
