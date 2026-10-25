#!/usr/bin/env python3
"""
Script de backup do histórico de conversas do Antigravity para o repositório NetSpot.
Copia os logs brutos da sessão atual para .agents/historico_chat/ (ignorado pelo .gitignore).
"""

import glob
import os
import shutil
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST_DIR = os.path.join(BASE_DIR, ".agents", "historico_chat")
BRAIN_DIR = os.path.expanduser("~/.gemini/antigravity/brain")


def resolve_source_dir() -> str:
    """Localiza dinamicamente o diretório de logs da conversa principal mais recente."""
    explicit_dir = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ANTIGRAVITY_LOG_DIR")
    if explicit_dir:
        return explicit_dir

    pattern = os.path.join(BRAIN_DIR, "*", ".system_generated", "logs", "transcript.jsonl")
    candidates = glob.glob(pattern)
    if not candidates:
        return ""

    # Prioriza conversas principais (que contêm interações diretas USER_EXPLICIT) sobre subagentes
    user_conversations = []
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                head = f.read(65536)
                if '"USER_EXPLICIT"' in head:
                    user_conversations.append(path)
        except OSError:
            continue

    pool = user_conversations if user_conversations else candidates
    latest_transcript = max(pool, key=os.path.getmtime)
    return os.path.dirname(latest_transcript)


def sync_chat_backup():
    os.makedirs(DEST_DIR, exist_ok=True)
    source_dir = resolve_source_dir()
    if not source_dir or not os.path.exists(source_dir):
        print(f"[ERRO] Diretório de origem não encontrado em: {BRAIN_DIR}", file=sys.stderr)
        return False

    copied = 0
    for fname in ["transcript.jsonl", "transcript_full.jsonl"]:
        src_path = os.path.join(source_dir, fname)
        dst_path = os.path.join(DEST_DIR, fname)
        if os.path.isfile(src_path):
            shutil.copy2(src_path, dst_path)
            size_kb = os.path.getsize(dst_path) / 1024
            print(f"[OK] Backup sincronizado: {fname} ({size_kb:.1f} KB) <- {source_dir}")
            copied += 1

    return copied > 0


if __name__ == "__main__":
    success = sync_chat_backup()
    sys.exit(0 if success else 1)

