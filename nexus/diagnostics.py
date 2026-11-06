"""Crash-safe diagnostics with limited, sanitized persistent logs.

No microphone WAV, API tokens, request bodies or model prompts are logged here.
When sharing logs, review them for filenames and project-specific information.
"""
from __future__ import annotations

import asyncio
import faulthandler
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import sys
import threading
import traceback

ROOT = Path(__file__).resolve().parent.parent
LOGS = Path(os.environ.get('NEXUS_LOG_DIR') or ROOT / 'logs')
LOGGER = logging.getLogger('nexus')
_INSTALLED = False
_CRASH_HANDLE = None

_SECRET = re.compile(
    r'(?i)(?:sk-[a-z0-9_-]{15,}|gsk_[a-z0-9_-]{15,}|hf_[a-z0-9_-]{15,}|'
    r'(?:(?:api[_-]?key|authorization|bearer|password|token)\s*[=:]\s*)[^\s,;}]+)'
)


def sanitize(value) -> str:
    text = re.sub(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{10,}', '[CREDENCIAL_OCULTA]', str(value))
    text = re.sub(r'AIza[0-9A-Za-z_-]{20,}', '[CREDENCIAL_OCULTA]', text)
    text = re.sub(r'(?i)([\"\']?(?:api[_-]?key|authorization|password|token|secret)[\"\']?\s*[:=]\s*)[\"\'][^\"\']*[\"\']', r'\1\"[CREDENCIAL_OCULTA]\"', text)
    return _SECRET.sub('[CREDENCIAL_OCULTA]', text)


class SanitizeFilter(logging.Filter):
    def filter(self, record):
        try:
            record.msg = sanitize(record.getMessage())
            record.args = ()
        except Exception:
            record.msg = '[Erro ao serializar evento de log]'
            record.args = ()
        return True


def install() -> None:
    global _INSTALLED, _CRASH_HANDLE
    if _INSTALLED: return
    LOGS.mkdir(parents=True, exist_ok=True)
    LOGGER.setLevel(logging.INFO)
    h = RotatingFileHandler(LOGS / 'nexus.log', maxBytes=2_000_000,
                            backupCount=4, encoding='utf-8')
    h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s [%(threadName)s] %(message)s'))
    h.addFilter(SanitizeFilter())
    LOGGER.addHandler(h)
    LOGGER.propagate = False
    _CRASH_HANDLE = open(LOGS / 'falha_fatal.log', 'a', encoding='utf-8', buffering=1)
    try:
        faulthandler.enable(file=_CRASH_HANDLE, all_threads=True)
    except Exception as e:
        LOGGER.warning('faulthandler indisponível: %s', e)
    old_sys_hook = sys.excepthook
    def sys_hook(typ, exc, tb):
        error('Exceção principal', exc, (typ, exc, tb))
        old_sys_hook(typ, exc, tb)
    sys.excepthook = sys_hook
    old_thread_hook = threading.excepthook
    def thread_hook(args):
        error(f'Exceção em thread {getattr(args.thread,"name", "?")}', args.exc_value,
              (args.exc_type, args.exc_value, args.exc_traceback))
        old_thread_hook(args)
    threading.excepthook = thread_hook
    _INSTALLED = True
    info('diagnóstico inicializado', python=sys.version.split()[0], pid=os.getpid())


def info(event_name: str, **fields):
    if not _INSTALLED: install()
    body = ' '.join(f'{k}={sanitize(v)[:180]}' for k,v in fields.items())
    LOGGER.info('%s %s', sanitize(event_name), body)


def warning(event_name: str, **fields):
    if not _INSTALLED: install()
    body=' '.join(f'{k}={sanitize(v)[:180]}' for k,v in fields.items())
    LOGGER.warning('%s %s', sanitize(event_name), body)


def error(event_name: str, exc: BaseException, exc_info=None):
    if not _INSTALLED: install()
    if exc_info is None:
        exc_info=(type(exc),exc,exc.__traceback__)
    trace=''.join(traceback.format_exception(*exc_info))
    LOGGER.error('%s: %s\n%s', sanitize(event_name),sanitize(exc),sanitize(trace))


def install_asyncio(loop):
    def handler(_loop, context):
        exc=context.get('exception')
        if isinstance(exc, BaseException):error('Erro no loop assíncrono', exc)
        else:warning('Erro no loop assíncrono', message=context.get('message','?'))
    loop.set_exception_handler(handler)


def install_qt():
    try:
        from PyQt6.QtCore import qInstallMessageHandler
        def qt_handler(_kind, _context, message):
            if message:
                warning('Qt', message=sanitize(message)[:500])
        # Keep the callback referenced for process lifetime.
        global _QT_HANDLER
        _QT_HANDLER=qt_handler
        qInstallMessageHandler(qt_handler)
    except Exception as exc:
        warning('Qt handler indisponível', reason=type(exc).__name__)


def report_path() -> str:
    return str(LOGS)
