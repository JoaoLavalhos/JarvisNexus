"""Explicit ordered OpenCode permission rules, scoped to this Nexus workspace."""
from pathlib import Path
import json

# Ordered V2 rules: last matching rule wins.
# Reads/edits inside the selected workspace are routine. Shell is arbitrary code,
# so only explicitly harmless commands are autoapproved; deletion and unknown
# scripts must still be reviewed. external_directory always asks.
DEFAULT_RULES = [
    {'action': name, 'resource': '*', 'effect': 'allow'}
    for name in ('read','glob','grep','edit','skill','question')
] + [
    {'action': 'read', 'resource': '*.env', 'effect': 'ask'},
    {'action': 'read', 'resource': '*.env.*', 'effect': 'ask'},
    {'action': 'read', 'resource': '*api_keys.json', 'effect': 'ask'},
    {'action': 'external_directory', 'resource': '*', 'effect': 'ask'},
    {'action': 'shell', 'resource': '*', 'effect': 'ask'},
] + [
    {'action': 'shell', 'resource': command, 'effect': 'allow'}
    for command in ('git status *','git diff *','git log *','git rev-parse *',
                    'git branch --show-current *','git ls-files *',
                    'Get-Location *','pwd *','Get-Date *')
]


def validate_rules(rules):
    if not isinstance(rules,list) or len(rules)>100:
        raise ValueError('Informe uma lista com até 100 regras.')
    result=[]
    for rule in rules:
        if not isinstance(rule,dict) or set(rule)!={'action','resource','effect'}:
            raise ValueError('Cada regra precisa de action, resource e effect.')
        if rule['effect'] not in ('allow','ask','deny') or not all(isinstance(rule[k],str) and rule[k].strip() for k in rule):
            raise ValueError('Regra inválida. Efeitos: allow, ask, deny.')
        resource=rule['resource'].strip()
        if rule['effect']=='allow' and rule['action'] in ('shell','external_directory'):
            if resource in ('*','**','/','C:/','C:\\','C:/**','C:\\**'):
                raise ValueError('Use um caminho ou comando específico para autorizar acesso externo/comandos.')
        result.append(dict(rule))
    return result


def load_rules(workspace):
    path=Path(__file__).resolve().parent.parent/'config'/'nexus_permissions.json'
    try:
        data=json.loads(path.read_text(encoding='utf-8'))
        return validate_rules(data.get(str(Path(workspace).resolve()),DEFAULT_RULES))
    except (OSError,ValueError,TypeError):return list(DEFAULT_RULES)


def save_rules(workspace,rules):
    rules=validate_rules(rules)
    path=Path(__file__).resolve().parent.parent/'config'/'nexus_permissions.json'
    try:data=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):data={}
    data[str(Path(workspace).resolve())]=rules
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
