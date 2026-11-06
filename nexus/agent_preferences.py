"""Local Nexus-only agent preferences; never changes global OpenCode settings."""
import json
from pathlib import Path
PATH=Path(__file__).resolve().parent.parent/'config'/'nexus_agent.json'

def load_preferences():
    try:
        data=json.loads(PATH.read_text(encoding='utf-8'))
        return data if isinstance(data,dict) else {}
    except (OSError,ValueError):return {}

def save_preferences(workspace,mode,model,variant,quick_chat):
    PATH.parent.mkdir(exist_ok=True,parents=True)
    data={'workspace':str(workspace),'mode':mode,'model':model,'variant':variant,'quick_chat':bool(quick_chat)}
    temp=PATH.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(PATH)
