"""Local verification of concrete file/line-count requests, independent of prose."""
from pathlib import Path
import hashlib
import re
import sys

EDIT=re.compile(r'\b(?:fa[çc]a|fazer|transforme|transformar|converta|converter|crie|criar|altere|alterar|modifique|modificar|ajuste|ajustar|corrija|corrigir|edite|editar|escreva|escrever|deixe|deixar|implemente|implementar)\b',re.I)


def is_html_edit_request(text):
    """Detect website editing requests even when spoken without the word HTML."""
    return bool(re.search(r'\b(?:html|htm|site|p[aá]gina|arquivo\s+longo|c[oó]digo\s+html)\b',text or '',re.I))

def requested_lines(text):
    if not EDIT.search(text or ''):return None
    match=re.search(r'\b(mil|\d[\d.]{1,6})\s+linhas?\b',text,re.I)
    if not match:return None
    value=1000 if match[1].lower()=='mil' else int(match[1].replace('.',''))
    return value if 2<=value<=100000 else None


def looks_like_chocolate_catalog(text, target=None):
    """Use specialized chocolate catalog helper only for relevant existing pages."""
    if re.search(r'\b(?:cacau\s+show|chocolate|trufa|bombom|cacau)\b', text or '', re.I):
        return True
    if not target:
        return False
    path = Path(target)
    try:
        # Read only a limited amount of the locally selected source file.
        if path.suffix.lower() not in ('.html', '.htm') or path.stat().st_size > 3_000_000:
            return False
        with path.open('r', encoding='utf-8', errors='replace') as f:
            sample = f.read(35000)
        return bool(re.search(r'\b(?:cacau\s+show|chocolate|trufa|bombom)\b', sample, re.I))
    except (OSError, UnicodeError):
        return False

def file_instruction(text, target=None):
    instruction=(
        'Em tarefas de arquivos, altere o arquivo solicitado pelo usuário; não troque por outro nome sem necessidade. '
        'Para arquivos extensos, prefira um pequeno script gerador executado pela ferramenta shell ou edições em blocos. '
        'Não gaste a resposta gerando um patch monolítico de milhares de linhas. '
        'Edições de arquivos no workspace já autorizado não exigem confirmação. Comandos shell e acessos externos podem exigir aprovação. Se usar Python, grave UTF-8 e confira o caminho absoluto. '
        'Após editar, releia o arquivo e verifique os requisitos com uma ferramenta. '
        'Só informe que o arquivo foi alterado se a gravação foi confirmada. ')
    count=requested_lines(text)
    if count:
        instruction+='ESTRATÉGIA OBRIGATÓRIA PARA ESTE ARQUIVO EXTENSO: use a ferramenta shell com um script Python ou PowerShell compacto para gerar e salvar o conteúdo. Não use a ferramenta patch, nem para criar o gerador. Crie o gerador pelo próprio shell (por exemplo, uma here-string) e execute-o. Mantenha o gerador compacto; use estruturas de dados e laços para produzir o HTML final. '
        instruction+=f'O pedido exige {count} linhas reais no arquivo final: conte com len(texto.splitlines()), sem comentários que apenas afirmem a contagem, e corrija até atingir o total. '
    if target:instruction+=f'Arquivo alvo escolhido e já confirmado como existente no painel: {target}. Leia esse caminho diretamente com a ferramenta read; não é necessário pesquisar Desktop ou testar a existência pelo shell. '
    if count and target and Path(target).suffix.lower() in ('.html','.htm') and looks_like_chocolate_catalog(text, target):
        helper=Path(__file__).with_name('html_builder.py')
        quote=lambda value: "'"+str(value).replace("'","''")+"'"
        command='& '+quote(sys.executable)+' '+quote(helper)+' --source '+quote(target)+' --lines '+str(count)
        instruction+='OTIMIZAÇÃO DISPONÍVEL PARA ESTE CATÁLOGO: o aplicativo já inclui um gerador local de página responsiva que lê o título e os produtos do arquivo original, cria backup e confere a contagem. Neste pedido, não gere um script novo: execute diretamente pela ferramenta shell este comando curto já preparado: '+command+'. A saída JSON já informa caminho, linhas e backup. Depois use read para conferir o HTML; o aplicativo também valida a contagem. Não é necessário criar outro comando Python -c com muitas aspas para conferir. Não use question para perguntar se pode executar: o usuário já pediu essa edição. Acione a ferramenta shell e aguarde a autorização nativa que o aplicativo exibirá. '
    if count:instruction+=f'O interpretador Python do aplicativo já está validado: {sys.executable} (Python {sys.version_info.major}.{sys.version_info.minor}). No PowerShell use & seguido desse caminho entre aspas. Não é necessário executar python --version. '
    return instruction


def paths_from_input(value, workspace):
    result=set()
    def walk(obj):
        if isinstance(obj,dict):
            for v in obj.values():walk(v)
        elif isinstance(obj,list):
            for v in obj:walk(v)
        elif isinstance(obj,str):
            patterns=[r'(?im)^\*\*\* (?:Add|Update) File:\s*(.+?\.html?)\s*$',
                      r'''(?i)([A-Z]:[\\/][^\r\n"'<>|]*?\.html?)''',
                      r'''(?i)(?:["']|^)([\w .\-/]+\.html?)(?:["']|$)''']
            for pattern in patterns:
                for match in re.finditer(pattern,obj):
                    name=match[1].strip()
                    if '://' in name:continue
                    path=Path(name)
                    if not path.is_absolute():path=Path(workspace)/path
                    try:result.add(path.resolve())
                    except OSError:pass
    walk(value)
    return result


def snapshot(path):
    path=Path(path)
    try:
        if path.stat().st_size>8_000_000:return None
        data=path.read_bytes();text=data.decode('utf-8-sig',errors='replace')
        return {'path':str(path.resolve()),'sha256':hashlib.sha256(data).hexdigest(),'lines':len(text.splitlines()),'bytes':len(data)}
    except (OSError,ValueError):return None


def verify_lines(count, candidates):
    evidence=[item for p in sorted(set(map(Path,candidates)),key=str) if (item:=snapshot(p))]
    matching=[item for item in evidence if item['lines']==count]
    if matching:return matching,None
    detail='; '.join(f"{Path(item['path']).name}: {item['lines']} linhas" for item in evidence) or 'nenhum arquivo HTML final foi localizado nos caminhos usados pela tarefa'
    return evidence,f'Verificação local: o pedido exige {count} linhas, mas {detail}. A alteração ainda não atende ao pedido.'
