#!/usr/bin/env bash
# Backup diario: banco (copia consistente), Excels e logs resumidos -> repo privado de backup.
# Nunca inclui .env. Uso: deploy/backup.sh   (cron: 30 3 * * *)
set -euo pipefail
APP="${FUNDO_APP:-$HOME/monitor-acoes}"
BKP="${FUNDO_BACKUP_REPO:-$HOME/fundo-backup}"
cd "$BKP"
mkdir -p db modelos
if [ -f "$APP/data/fundo.db" ]; then
  sqlite3 "$APP/data/fundo.db" ".backup '$BKP/db/fundo.db'"
fi
if [ -d "$APP/data/fontes" ]; then   # copias dos documentos citados nas premissas (auditoria)
  mkdir -p fontes
  rsync -a "$APP/data/fontes/" "$BKP/fontes/"
fi
if [ -d "$APP/valuation/models" ]; then
  rsync -a --delete "$APP/valuation/models/" "$BKP/modelos/" 2>/dev/null || cp -r "$APP/valuation/models/." "$BKP/modelos/"
fi
git add -A
if ! git diff --cached --quiet; then
  git -c user.name="fundo-vm" -c user.email="fundo-vm@users.noreply.github.com" \
      commit -qm "backup $(date -Iseconds)"
  git push -q origin HEAD
fi
echo "backup ok $(date -Iseconds)"
