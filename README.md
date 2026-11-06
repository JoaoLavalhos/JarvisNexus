# JARVIS NEXUS

> **Alpha / Active Development** — assistente pessoal experimental para Windows com voz, agentes de IA, execução de tarefas e uma arquitetura em evolução para memória persistente e múltiplos núcleos visuais.

<p align="center">
  <img src="assets/ignis-core-preview.jpg" alt="Prévia do IGNIS Core" width="100%" />
</p>

<p align="center"><sub><b>IGNIS Core</b> — nova interface do JarvisNexus em integração. A telemetria exibida nesta prévia é ilustrativa.</sub></p>

## Visão geral

O **JarvisNexus** é um projeto de assistente pessoal com IA focado em interação por voz, execução agente, automação no Windows e uma experiência visual própria.

A versão atual combina diferentes componentes para separar **escuta**, **conversa**, **execução profunda**, **voz**, **permissões** e **observabilidade**. O objetivo de longo prazo é transformar essa estrutura em um núcleo de agente próprio, modular e independente de um único framework ou provedor de IA.

O projeto começou a partir da exploração de um **projeto open source publicado no GitHub** e vem sendo progressivamente reestruturado em torno de uma arquitetura própria, com uma camada dedicada chamada `nexus/`.

## O que já existe

- **Groq Whisper Large V3** para reconhecimento de fala no fluxo Nexus;
- **Gemini Live** para interação/voz em fluxos compatíveis;
- **OpenCode + OpenAI** como backend de agente para tarefas mais profundas;
- camada própria `nexus/` para execução, estado de tarefas, preferências e integração do agente;
- monitoramento de execução com etapas, atividade e progresso;
- sistema de permissões para operações do agente;
- captura de tela aprovada pelo usuário para contexto visual do agente;
- logs locais de atividade e conversa para diagnóstico;
- configuração de modelo, modo e workspace;
- scripts de instalação, inicialização, diagnóstico e verificação no Windows;
- testes de regressão das versões do agente.

## Em desenvolvimento

- integração completa da interface **IGNIS Core**;
- múltiplos núcleos visuais selecionáveis;
- memória persistente / **Second Brain** com Obsidian;
- integração ampliada com **Skills e MCPs**;
- wake word local `Jarvis` no fluxo Nexus;
- roteamento mais avançado entre conversa rápida e agente profundo;
- núcleo próprio de orquestração para reduzir a dependência de OpenCode;
- provedores de modelos intercambiáveis.

## Arquitetura atual

```text
Microfone
   │
   ▼
Groq Whisper / Gemini Live
   │
   ▼
JARVIS NEXUS
   │
   ├── Conversa / voz
   │
   └── Agente profundo
          │
          ▼
     OpenCode + OpenAI
          │
          ▼
  Ferramentas / permissões
          │
          ├── arquivos e workspace
          ├── captura de tela
          ├── automação
          └── monitor de execução

Próxima camada:
Obsidian / memória persistente + Skills / MCP + IGNIS Core
```

## IGNIS Core

**IGNIS** é o primeiro núcleo visual desenvolvido para a nova identidade do JarvisNexus. A proposta é substituir uma interface estática por núcleos reativos que representem os estados do assistente — repouso, escuta, processamento, execução e fala.

A imagem acima mostra a direção visual em desenvolvimento. O sistema exibido na prévia ainda está sendo conectado ao backend real do JarvisNexus, por isso os dados de telemetria mostrados nela são simulados.

## Estrutura do projeto

```text
actions/      Ações e automações disponíveis ao assistente
core/         Componentes centrais de voz, áudio, Gemini e runtime
memory/       Camada de memória existente
nexus/        Camada própria do JarvisNexus para agente e orquestração
providers/    Provedores de STT, LLM e TTS
plugins/      Sistema de extensões
scripts*      Instalação, inicialização e diagnóstico no Windows
tests/        Testes de regressão do agente
assets/       Mídia pública do projeto
```

## Instalação da V19

### Requisitos principais

- Windows
- Python 3.12
- OpenCode instalado e autenticado para o modo de agente
- chave Groq própria para o fluxo de STT
- credenciais dos provedores que você optar por utilizar

### Preparação

No PowerShell, dentro da pasta do projeto:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\INSTALAR.ps1
```

Configure o Groq pelo fluxo local do projeto:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\CONFIGURAR-GROQ.ps1
```

Antes de iniciar, rode a verificação da versão:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\VERIFICAR-V19.ps1
```

Depois:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\INICIAR-NEXUS.ps1
```

Também existe `INICIAR-NEXUS.bat` para inicialização direta no Windows.

## Privacidade e arquivos locais

Credenciais, gravações de diagnóstico e logs locais **não devem ser enviados ao repositório**. O `.gitignore` exclui, entre outros:

- `config/api_keys.json`;
- `.env` e arquivos de segredo;
- `logs/`;
- gravações `.wav`, `.mp3` e `.flac`;
- `diagnostico_groq/`;
- ambientes virtuais Python.

O `Activity.log`, quando habilitado localmente, pode conter conversas completas. Revise qualquer log antes de compartilhá-lo.

## Estado do projeto

O JarvisNexus está em **desenvolvimento ativo**. Algumas partes da V19 já funcionam como infraestrutura do agente, enquanto outras — principalmente a nova interface IGNIS, memória persistente e a futura orquestração própria — estão em processo de integração.

A intenção deste repositório é também registrar essa evolução técnica, em vez de apresentar o projeto como finalizado.

## Origem

O desenvolvimento atual do **JarvisNexus** é de **João Lavalhos**. O projeto nasceu a partir da análise e experimentação com uma base open source disponível no GitHub e vem sendo progressivamente transformado em uma arquitetura própria.

---

**JarvisNexus** — voz, agentes, memória e presença em uma única arquitetura em evolução.
