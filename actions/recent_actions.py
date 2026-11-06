"""Disponibiliza os registros de execução ao próprio assistente.

Evita que o assistente negue ações que foram realmente executadas.
"""
from nexus import activity


def recent_actions(parameters: dict, **kwargs) -> str:
    return activity.describe(parameters.get("limit", 8))


TOOL = {
    "name": "recent_actions",
    "description": (
        "Verifique o histórico de ferramentas realmente executadas NESTA sessão. "
        "USE SEMPRE que a pessoa perguntar 'foi você que abriu?', 'você fez isso?', "
        "'que ações tomou?' ou 'qual foi a última coisa que fez?'. "
        "Se não houver registro, diga que não pode confirmar. Nunca negue uma "
        "ação registrada ou alegue sucesso a partir de um resultado não verificado."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {"limit": {"type": "INTEGER", "description": "Quantidade: de 1 a 30"}},
        "required": [],
    },
    "handler": recent_actions,
}
