"""Task lifecycle independent of speech and translated status messages."""
from __future__ import annotations
from enum import StrEnum
import json
import threading
import time
import uuid
from pathlib import Path


class Phase(StrEnum):
    READY = 'ready'
    RUNNING = 'running'
    WAITING_PERMISSION = 'waiting_permission'
    STOPPING = 'stopping'
    SUCCEEDED = 'succeeded'
    FAILED = 'failed'
    CANCELLED = 'cancelled'
    RECOVERY_REQUIRED = 'recovery_required'


TERMINAL = {Phase.SUCCEEDED, Phase.FAILED, Phase.CANCELLED}


class TaskState:
    def __init__(self, path=None, callback=None):
        self.path = Path(path) if path else None
        self.callback = callback or (lambda _: None)
        self.lock = threading.RLock()
        self.value = {'id': '', 'phase': Phase.READY, 'started': None, 'updated': time.time()}
        if self.path and self.path.exists():
            try:
                old = json.loads(self.path.read_text(encoding='utf-8'))
                if old.get('phase') in ('running', 'waiting_permission', 'stopping'):
                    old.update(phase='recovery_required', detail='A execução anterior terminou sem confirmação. Reconecte o agente.')
                self.value = old
            except (OSError, ValueError, TypeError):
                pass

    def begin(self, model=None):
        with self.lock:
            self.value = {'id': uuid.uuid4().hex, 'phase': Phase.READY, 'started': time.time(),
                          'model': (model or {}).get('id', 'padrão do OpenCode')}
            return self.set(Phase.RUNNING)

    def set(self, phase, detail=''):
        with self.lock:
            self.value.update(phase=str(phase), detail=str(detail)[:800], updated=time.time())
            snapshot = dict(self.value)
            if self.path:
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self.path.with_suffix('.tmp')
                    temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
                    temporary.replace(self.path)
                except OSError as exc:
                    from nexus import diagnostics as diag
                    diag.warning('task.persistence.failed', reason=type(exc).__name__)
        self.callback({'type': 'nexus.task.state', 'properties': snapshot})
        return snapshot

    def snapshot(self):
        with self.lock:
            return dict(self.value)
