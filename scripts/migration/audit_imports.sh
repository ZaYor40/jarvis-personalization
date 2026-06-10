#!/usr/bin/env bash
# Audit des imports différés inter-packages — thermomètre de la migration.
#
# - Section 1 : imports indentés `from <pkg>` hors tests et hors TYPE_CHECKING
#   (les imports différés sont la principale forme de couplage caché qu'on doit éliminer).
# - Section 2 : fichiers concernés (compte unique).
# - Section 3 : imports DYNAMIQUES (`__import__(...)`, `import_module(...)`) qui
#   échappent aux greps `^from` mais font partie du même problème de couplage —
#   notamment les 14+ `__import__("tools.X")` dans voice_agent.py l.144-197.
#
# Le résultat se lit dans le rapport de phase, pas dans un fichier de gate
# (sortie vers stdout ; la baseline numérique est notée dans le rapport A).
#
# Note portabilité : ce script utilise `grep -E` + classes POSIX (`[[:space:]]`)
# pour fonctionner identiquement sur macOS (BSD grep) et Linux (GNU grep).
# Le pattern `\s\+` du CDC v1.3 n'est pas reconnu par BSD grep — corrigé ici.

set -uo pipefail

PKGS="core|memory|tools|skills|agent|api|proactive|channels|background|llm|config|audio|vision|kernel|jarvis"

echo "== Imports différés inter-packages (statiques) =="
grep -rnE "^[[:space:]]+from ($PKGS)" --include="*.py" . \
  --exclude-dir=.git --exclude-dir=tests --exclude-dir=.venv \
  --exclude-dir=__pycache__ --exclude-dir=workspace \
  | grep -v "TYPE_CHECKING" | grep -v "# lazy:" | tee /tmp/lazy_imports.txt | wc -l

echo "== Fichiers concernés =="
cut -d: -f1 /tmp/lazy_imports.txt | sort -u | wc -l

echo "== Imports DYNAMIQUES (échappent aux greps ^from — à réécrire aussi en Phase B) =="
grep -rnE "import_module\(|__import__\(" --include="*.py" . \
  --exclude-dir=.git --exclude-dir=tests --exclude-dir=.venv \
  --exclude-dir=__pycache__ --exclude-dir=workspace \
  | grep -E '"(core|llm|memory|tools|skills|agent|api|proactive|background|channels|audio|vision)\.'
