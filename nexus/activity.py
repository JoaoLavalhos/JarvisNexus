"""Registro local e efêmero de ações reais para evitar falsos relatos.

Não grava conteúdo das solicitações, credenciais ou histórico de navegação.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from threading import RLock

_guard = RLock()
_events = deque(maxlen=60)
_last_utterance = ""


def set_user_utterance(text: str) -> None:
    global _last_utterance
    with _guard:
        _last_utterance = (text or "").strip()[:1200]


def last_user_utterance() -> str:
    with _guard:
        return _last_utterance


def _status(result: object) -> str:
    text = str(result or "")
    if text.startswith("status=done "):
        return "confirmado"
    if text.startswith("status=failed ") or " failed:" in text or text.startswith("ERR:"):
        return "falhou"
    if text.startswith("status=ask "):
        return "aguardando confirmação"
    if text.startswith("status=started "):
        return "iniciado; aguardando verificação"
    return "resultado não verificado"


def record(tool: str, result: object) -> dict:
    event = {
        "hora": datetime.now().strftime("%H:%M:%S"),
        "ferramenta": str(tool or "desconhecida")[:60],
        "estado": _status(result),
        "resumo": str(result or "")[:230].replace("\n", " "),
    }
    # O resultado de ferramentas pode conter conteúdo sensível: não o armazenamos.
    # Preserve somente um resumo no tempo de vida do processo; sem arquivo em disco.
    with _guard:
        _events.append(event)
    return event


def recent(limit: int = 8) -> list[dict]:
    with _guard:
        return [dict(x) for x in list(_events)[-max(1, min(limit, 30)):]][::-1]


def describe(limit: int = 8) -> str:
    events = recent(limit)
    if not events:
        return "Nenhuma ferramenta executada nesta sessão. Não invente ações anteriores."
    lines = ["REGISTRO OBSERVÁVEL DA SESSÃO — mais recente primeiro:"]
    for event in events:
        lines.append(f"{event['hora']} | {event['ferramenta']} | {event['estado']} | {event['resumo']}")
    lines.append("Registros não verificados não comprovam a conclusão da ação.")
    return "\n".join(lines)


def context_for_question(text: str) -> str:
    """Anexa fatos curtos quando pergunta sobre atividades anteriores.

    Não cria chamadas de API extras; não altera o texto mostrado na interface.
    """
    if not text:
        return text
    plain = text.casefold()
    wants_audit = any(marker in plain for marker in (
        "foi você", "foi voce", "você abriu", "voce abriu",
        "você fez", "voce fez", "que ações", "que acoes",
        "o que você abriu", "o que voce abriu", "última ação", "ultima acao",
        "abriu alguma", "abriu essa", "abriu aquela", "fez alguma",
    ))
    if not wants_audit:
        return text
    return (text + "\n\n[REGISTRO LOCAL DE AÇÕES EXECUTADAS NESTA SESSÃO]\n"
            + describe(5) + "\n[INSTRUÇÃO DO APLICATIVO] "
            "Baseie sua resposta nestes registros, não invente nem negue ações. "
            "Um resultado não verificado não prova conclusão.")
