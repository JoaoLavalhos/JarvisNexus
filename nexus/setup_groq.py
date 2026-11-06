"""Securely set or check the GROQ_API_KEY used by the working Mark-LVI patch."""
from __future__ import annotations
import getpass
import sys

SERVICE = 'GroqTeste-Jarvis'
USER = 'GROQ_API_KEY'


def main():
    import keyring
    if len(sys.argv) > 1 and sys.argv[1] == '--check':
        found = bool(keyring.get_password(SERVICE, USER))
        print('Chave Groq:', 'ENCONTRADA no cofre' if found else 'NÃO ENCONTRADA')
        return 0 if found else 2
    api = getpass.getpass('Cole GROQ_API_KEY (não aparece na tela): ').strip()
    if not api or len(api) < 15:
        print('Chave inválida ou vazia.')
        return 1
    keyring.set_password(SERVICE, USER, api)
    print('Chave Groq salva no cofre do Windows. Nenhuma cópia foi salva em JSON.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
