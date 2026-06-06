from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from core.vocab import AccessLevel


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    WAITING_APPROVAL = "waiting_approval"
    SKIPPED = "skipped"


class ProjectStatus(StrEnum):
    PLANNING = "planning"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    KILLED = "killed"


@dataclass
class Step:
    id: str
    title: str
    description: str
    status: StepStatus = StepStatus.PENDING
    requires_approval: bool = False
    output: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    # Champs PHASE 0 — contrat de vérification (§3.4)
    success_criterion: str = ""
    verification_command: str | None = None
    access_level: AccessLevel = AccessLevel.WRITE_LOCAL
    verified: bool = False
    verification_notes: str | None = None


@dataclass
class Project:
    id: str
    title: str
    mission: str
    status: ProjectStatus = ProjectStatus.PLANNING
    steps: list[Step] = field(default_factory=list)
    workspace_path: str = ""
    timeout_minutes: int = 30
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    llm_calls: int = 0
    files_created: list[str] = field(default_factory=list)
    requires_network: bool = False


@dataclass
class LogEntry:
    timestamp: datetime
    level: str  # "info" | "tool" | "error" | "approval"
    message: str
    step_id: str | None = None
    data: Any = None


def validate_step(step: Step) -> None:
    """Valide qu'un Step porte un success_criterion non vide. Lève ValueError sinon.

    À appeler à la validation du plan (orchestrateur), pas à la construction (Option A §3.4).
    Le défaut `""` n'existe que pour la compatibilité ascendante : un step sans critère
    réel (vide ou blancs) doit toujours être rejeté.
    """
    if not step.success_criterion.strip():
        raise ValueError(f"Step '{step.id}' n'a pas de success_criterion.")
