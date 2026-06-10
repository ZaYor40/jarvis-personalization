# BACKLOG — Refonte architecturale jarvis-OS

Réceptacle des problèmes hors-périmètre identifiés pendant la refonte (CDC `CDC_refonte_architecture.md` §0 règle 1 et règle 5). On note, on ne corrige PAS dans la phase courante.

Format d'entrée : `- [PHASE X] <description> — <fichier/zone> — <pourquoi pas maintenant>`.

## Phase A

_(en cours)_

## Phase B

_(à venir)_

## Phase C

- **Bug PRÉ-EXISTANT dans `src/jarvis/app.py` lifespan shutdown** : `await telegram.stop()` (l.611) est appelé même quand l'updater Telegram n'a jamais démarré (cas typique : TELEGRAM_BOT_TOKEN défini mais polling non lancé en TestClient). Lève `RuntimeError("This Updater is not running!")`. À résoudre en C.1 (refactor du lifespan vers bootstrap.build()) : vérifier `_app.updater.running` avant de stop(), ou capturer proprement l'exception. Découvert par B7b qui est le 1er test à fermer proprement le lifespan via TestClient.

## Phase D

_(à venir)_

## Phase E

_(à venir)_

## Phase F

- **GATE B9 (install à froid) BLOQUANT pour le merge final** — décalé de fin de B sur décision Barth, doit passer sur la lane CI complète avant le merge `refonte/architecture-couches` → `main`. Libellé verrouillé dans [gates_B8_B9.md](gates_B8_B9.md) : install Ubuntu propre + deps lourdes réelles + boot effectif via smoke_runtime --fake-llm.
- **ci.yml déclenche la lane lourde (dlib/portaudio/opencv) sur toutes branches** → split en F.1.2 : lane rapide partout, lane complète sur main + scheduled. Coût ~5-10 min par push branche jusque-là, accepté.

## Post-refonte (hors §9 « Hors périmètre »)

- Retrait des shims racine `main.py` / `voice_agent.py` — conservés une version pour les appelants externes (CDC §9).
- Réécriture front (ES modules `capabilities.js` / `macropad_2k.js`) — CDC ultérieur.
- mypy strict généralisé sur 46k lignes — chantier séparé, seul kernel + conformité Protocols couverts par F.1.3bis.
- Git LFS / réécriture historique pour gros binaires.
