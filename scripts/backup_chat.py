#!/usr/bin/env python3
"""
Script de backup do histórico de conversas do Antigravity para o repositório NetSpot.
Copia os logs brutos da sessão atual para .agents/historico_chat/ (ignorado pelo .gitignore).
"""

import os
import shutil
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST_DIR = os.path.join(BASE_DIR, ".agents", "historico_chat")
SOURCE_DIR = "/home/crispim/.gemini/antigravity/brain/5a945ec5-d10f-4239-822b-a2a7c22db31c/.system_generated/logs"


def sync_chat_backup():
    os.makedirs(DEST_DIR, exist_ok=True)
    if not os.path.exists(SOURCE_DIR):
        print(f"[ERRO] Diretório de origem não encontrado: {SOURCE_DIR}", file=sys.stderr)
        return False

    copied = 0
    for fname in ["transcript.jsonl", "transcript_full.jsonl"]:
        src_path = os.path.join(SOURCE_DIR, fname)
        dst_path = os.path.join(DEST_DIR, fname)
        if os.path.isfile(src_path):
            shutil.copy2(src_path, dst_path)
            size_kb = os.path.getsize(dst_path) / 1024
            print(f"[OK] Backup sincronizado: {fname} ({size_kb:.1f} KB) -> {dst_path}")
            copied += 1

    return copied > 0


if __name__ == "__main__":
    success = sync_chat_backup()
    sys.exit(0 if success else 1)

