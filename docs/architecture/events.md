# `kernel.events` — Bus d'événements (CDC §6 Phase D)

Ce document est **la source de vérité unique** pour le bus pub/sub du noyau.
Chaque événement défini dans `src/jarvis/kernel/events.py` doit y figurer
avec son payload, ses émetteurs et ses abonnés. Gate D2 grep le fichier
pour vérifier l'exhaustivité — un événement ajouté sans entrée ici échoue
la gate.

## Principes

1. **Direction.** Le bus sert les communications **montantes**
   (couche basse → couche haute) et **transverses** que les RÈGLES de
   couches (§2.2) interdiraient en import direct. Il N'EST PAS un canal
   de remplacement pour les couplages synchrones intra-couche (cf. le
   pattern callback budget↔tracking, gardé tel quel).
2. **Câblage explicite.** Tous les abonnements vivent dans
   `bootstrap.py::_wire_events()`. Aucune auto-découverte, aucun
   décorateur magique. La table ci-dessous reflète ce câblage.
3. **Tolérance aux erreurs.** Le bus utilise `asyncio.gather(...,
   return_exceptions=True)` — un handler qui lève NE casse PAS les
   autres ; l'erreur est loguée via loguru.
4. **Immuabilité du payload.** Chaque dataclass d'événement est
   `frozen=True` — les handlers ne peuvent pas muter ce qu'ils
   reçoivent.

## Catalogue

### `MissionCompleted`

| Champ          | Type           | Description                                       |
| -------------- | -------------- | ------------------------------------------------- |
| `mission_id`   | `str`          | Identifiant du projet (cf. `Project.id`).         |
| `verdict`      | `str`          | `"success"` \| `"failure"` \| `"killed"`.         |
| `artifacts`    | `dict`         | (Optionnel) Métadonnées d'artefacts produits.     |
| `completed_at` | `datetime`     | Timestamp d'émission (par défaut `datetime.now`). |

**Émetteurs.**
- `engine/mission/worker_agent.py::WorkerAgent.run` (clause `finally`) —
  publie quand `project.status ∈ {DONE, FAILED, KILLED}` et qu'un bus a
  été injecté. Fallback : appel direct `_maybe_reflect()` pour les
  tests legacy qui injectent `reflexion=` sans `bus=`.

**Abonnés.**
- `bootstrap.py::_wire_events::_on_mission_completed` — résout
  `project_store.load_project(mission_id)`, puis appelle
  `reflexion.reflect(project)`. Dégrade silencieusement si le projet
  n'est pas retrouvé (mission externe, test isolé).

### `MemoryIngested`

| Champ         | Type       | Description                                                 |
| ------------- | ---------- | ----------------------------------------------------------- |
| `event_id`    | `str`      | ID de l'`Event` mémoire créé par `kernel.log_event(...)`.   |
| `fact_count`  | `int`      | Nombre de facts confirmés + nouveaux après réconciliation.  |
| `source`      | `str`      | Source de l'ingestion (`"conversation"`, `"reflexion:…"`).  |
| `ingested_at` | `datetime` | Timestamp d'émission (par défaut `datetime.now`).           |

**Émetteurs.**
- `providers/memory/ingest.py::MemoryIngest.ingest` — publie après le
  pipeline (`log_event → extract → reconcile`) si un bus a été injecté.

**Abonnés.**
- `bootstrap.py::_wire_events::_on_memory_ingested` — broadcast UI
  via `proactive_queue.broadcast_event({"type": "memory_ingested", …})`
  pour rafraîchir le compteur de facts sur le dashboard.

### `NotificationRequested`

| Champ      | Type     | Description                                       |
| ---------- | -------- | ------------------------------------------------- |
| `channel`  | `str`    | `"websocket"` \| `"telegram"` \| autre canal cible. |
| `payload`  | `dict`   | Données structurées passées tel quel au sink.     |
| `priority` | `str`    | `"low"` \| `"normal"` \| `"high"` (défaut `normal`). |

**Émetteurs.**
- Réservé pour les couches basses qui n'ont pas accès à un callback
  `broadcast_event` injecté. En Phase D, l'émetteur explicite reste à
  câbler au cas par cas — les call-sites historiques qui ont déjà un
  `broadcast_event` (worker, budget, etc.) gardent leur pattern pour
  ne pas casser la sémantique fine du payload.

**Abonnés.**
- `bootstrap.py::_wire_events::_on_notification_requested` — si
  `channel == "websocket"`, forward le payload à
  `proactive_queue.broadcast_event`. Sinon, lit `payload.content` et
  pousse vers `NotificationQueue.add()` (texte simple pour Telegram /
  mémoire utilisateur).

### `BudgetThresholdReached`

| Champ      | Type    | Description                                                                 |
| ---------- | ------- | --------------------------------------------------------------------------- |
| `ratio`    | `float` | `0.0` → `1.0` (`1.0` = hard-stop, sinon ≈ `spent/limit`).                   |
| `provider` | `str`   | Origine fonctionnelle : `"mission"` si scope `project:…`, `"global"` sinon. |
| `scope`    | `str`   | Scope du seuil (`"global"`, `"project:<id>"`, `"run:<id>"`).                 |

**Émetteurs.**
- `engine/budget.py::BudgetGuard.reserve` — publie à deux moments :
  - **Hard-stop** (projected > limit) : `ratio = 1.0`, refuse la
    réservation (`return False`).
  - **Warn** (status `warning`, une seule fois par scope par session) :
    `ratio = spent/limit`, autorise la réservation (`return True`).

**Abonnés.**
- `bootstrap.py::_wire_events::_on_budget_threshold` — broadcast UI
  via `proactive_queue.broadcast_event({"type": "budget_hard_stop"|
  "budget_warning", …})` ; pour les hard-stops, ajoute aussi un texte
  à `NotificationQueue` pour signaler l'arrêt à l'utilisateur.

## Ajouter un événement

1. Définir la dataclass `@dataclass(frozen=True)` dans
   `src/jarvis/kernel/events.py`. Le payload reste sérialisable (types
   stdlib + dataclasses kernel.schemas).
2. Câbler le handler dans `bootstrap.py::_wire_events()` — pas
   d'auto-découverte.
3. Mettre à jour ce fichier avec : payload, émetteur(s), abonné(s).
4. Ajouter un test d'intégration émetteur→handler dans
   `tests/test_phase_d_bus_wiring.py` (ou un test dédié).
5. La gate D2 grep le nom de la dataclass dans ce document — un
   événement non documenté échoue.

## Tests

- Unitaires bus (publish/subscribe/erreur isolée) :
  `tests/test_kernel_events.py`.
- Intégration émetteur → événement publié :
  `tests/test_phase_d_bus_wiring.py`.
- Câblage handler complet : à compléter au fil de l'eau (PHASE D.E)
  quand les call-sites historiques migreront du callback vers le bus.
