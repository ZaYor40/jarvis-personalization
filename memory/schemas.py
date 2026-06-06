"""Contrats de données Memory Kernel — structures pures, aucune logique (§3.5, §6.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class FactStatus(StrEnum):
    """Cycle de vie d'un fact (§3.5)."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    CONFLICTED = "conflicted"
    ARCHIVED = "archived"
    NEEDS_REVIEW = "needs_review"


class DecayPolicy(StrEnum):
    """Politique de décroissance de saillance au retrieval (§3.5, §6.6)."""

    NONE = "none"
    VERY_SLOW = "very_slow"
    SLOW = "slow"
    MEDIUM = "medium"
    FAST = "fast"


class ObservationType(StrEnum):
    """Type d'observation sur un fact existant (§6.2 — fact_observations)."""

    CONFIRM = "confirm"
    WEAKEN = "weaken"
    CORRECT = "correct"


class RelationType(StrEnum):
    """Nature du lien entre deux facts (§6.2 — fact_relations)."""

    SUPERSEDES = "supersedes"
    CONTRADICTS = "contradicts"
    SUPPORTS = "supports"
    RELATED_TO = "related_to"


@dataclass
class Event:
    """Log immuable de tout ce qui arrive — on ne supprime jamais un event brut (§6.2)."""

    id: str
    type: str
    source: str
    content: str
    created_at: datetime = field(default_factory=datetime.now)
    metadata_json: str | None = None


@dataclass
class Fact:
    """Claim atomique : une idée par fact (§6.2, §6.3).

    predicate ∈ PREDICATES et category ∈ CATEGORIES sont validés à l'ingestion (§3.1).
    Un fact hors vocabulaire reçoit status=NEEDS_REVIEW et n'entre pas en base principale.
    """

    id: str
    subject: str
    predicate: str  # ∈ PREDICATES — validé par l'ingestion
    object: str  # noqa: A003 — nom imposé par le schéma relationnel §6.2
    category: str  # ∈ CATEGORIES — validé par l'ingestion
    status: FactStatus = FactStatus.ACTIVE
    confidence: float = 0.55
    support_count: int = 1
    decay_policy: DecayPolicy = DecayPolicy.MEDIUM
    # PHASE 3 (changement de contrat PHASE 0 signalé) — importance pour le ranking
    # retrieval (§6.9, formule Generative Agents : importance × récence × pertinence × confidence).
    # Notée par le LLM à l'ingestion sur [0, 1] ; défaut 0.5 si non précisée.
    importance: float = 0.5
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    source_event_id: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    last_seen_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class FactObservation:
    """Renforcement ou correction d'un fact sans duplication (§6.2, §6.5)."""

    id: str
    fact_id: str
    event_id: str
    observation_type: ObservationType
    confidence_delta: float
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class FactRelation:
    """Lien typé entre deux facts (§6.2)."""

    id: str
    from_fact_id: str
    to_fact_id: str
    relation_type: RelationType
    created_at: datetime = field(default_factory=datetime.now)
