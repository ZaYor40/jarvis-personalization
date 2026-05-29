"""CLI sandboxé pour le WorkerAgent — whitelist stricte + exécution dans le workspace."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from loguru import logger

WORKER_CLI_WHITELIST: list[str] = [
    "python", "python3",
    "node", "npm", "npx",
    "git clone", "git init", "git add", "git status", "git log", "git diff",
    "pip install", "pip3 install",
    "mkdir", "touch", "cp", "mv",
    "ls", "cat", "head", "tail", "grep", "find", "wc",
    "echo", "printf",
    "curl -s", "curl --silent",
    "wget",
    "ffmpeg", "convert",
    "zip", "unzip", "tar",
    "uv", "uv run", "uv add",
    "pandoc", "pdftotext",
    "stat", "diff", "du", "sort", "uniq", "cut", "tr", "sed", "awk",
    "test", "true", "false",
]

# Patterns bloqués inconditionnellement dans chaque segment de commande
_BLOCKED_RE = re.compile(
    r"rm\s+-[a-z]*r"                          # suppression récursive
    r"|rm\s+-[a-z]*f"                         # suppression forcée
    r"|>>?\s*/[a-zA-Z]"                       # redirection vers chemin absolu
    r"|\bsudo\b"
    r"|chmod\s+777"
    r"|curl\s+-X\s+POST"
    r"|curl\s+-X\s+DELETE"
    r"|git\s+push"
    r"|git\s+commit"
    r"|:\(\)\s*\{"                            # fork bomb
    r"|\bos\.system\s*\("                     # appel système Python
    r"|\bsubprocess\b"                        # module subprocess Python
    r"|\beval\s*\("                           # évaluation dynamique
    r"|\bexec\s*\("                           # exécution dynamique
    r"|base64\s+(?:-d|--decode)"              # décodage base64 (obfuscation)
    r"|\|\s*(?:sh|bash|python3?|zsh|ksh)\b",  # pipe vers interpréteur shell
    re.IGNORECASE,
)

# Découpe les chaînes de commandes séparées par && ou ;
_SEP_RE = re.compile(r"\s*(?:&&|;)\s*")

# Détecte un flag -c ou un guillemet dans une commande python/python3
_PYTHON_INLINE_RE = re.compile(r"\s+-c\b|['\"`]")


class WorkerCLITool:

    def __init__(
        self,
        workspace_path: str,
        docker_executor: object | None = None,
    ) -> None:
        self._workspace = Path(workspace_path).resolve()
        self._docker    = docker_executor  # None = V1 direct, DockerExecutor = V2

    def _check_segment(self, segment: str) -> dict | None:
        """Valide un segment de commande individuel ; retourne un dict d'erreur ou None."""
        stripped = segment.strip()
        if not stripped:
            return None

        if _BLOCKED_RE.search(stripped):
            logger.error("WorkerCLI blocked", command=stripped[:80])
            return {
                "success": False, "stdout": "",
                "stderr": f"Commande bloquée par la politique de sécurité : {stripped[:60]}",
                "returncode": -1,
            }

        if not any(stripped.startswith(w) for w in WORKER_CLI_WHITELIST):
            logger.warning("WorkerCLI not whitelisted", command=stripped[:80])
            return {
                "success": False, "stdout": "",
                "stderr": (
                    f"Commande non autorisée. Commandes permises : "
                    f"{', '.join(WORKER_CLI_WHITELIST[:8])}..."
                ),
                "returncode": -1,
            }

        # python/python3 : seule l'exécution de fichiers .py est autorisée
        if re.match(r"python3?\s", stripped) and _PYTHON_INLINE_RE.search(stripped):
            logger.error("WorkerCLI python inline bloqué", command=stripped[:80])
            return {
                "success": False, "stdout": "",
                "stderr": (
                    "Exécution Python en ligne (-c / guillemets) interdite. "
                    "Utilisez un fichier .py : python3 script.py"
                ),
                "returncode": -1,
            }

        return None

    def _check(self, command: str) -> dict | None:
        """Valide la commande complète segment par segment (sépare && et ;)."""
        for segment in _SEP_RE.split(command):
            err = self._check_segment(segment)
            if err:
                return err
        return None

    async def execute(self, command: str, timeout: int = 60) -> dict:  # noqa: ASYNC109
        """Exécute une commande. Route vers Docker (V2) ou direct (V1) si opt-in explicite."""
        err = self._check(command)
        if err:
            return err

        from config.settings import settings

        if self._docker and settings.docker_enabled:
            return await self._docker.execute(command, timeout)

        if not settings.allow_unsandboxed_exec:
            logger.error(
                "WorkerCLI: exécution directe refusée "
                "(docker_enabled=False, allow_unsandboxed_exec=False)"
            )
            return {
                "success": False, "stdout": "",
                "stderr": (
                    "Exécution refusée : aucun sandbox actif. "
                    "Activez Docker (DOCKER_ENABLED=true, recommandé) "
                    "ou autorisez explicitement l'exécution hôte "
                    "(ALLOW_UNSANDBOXED_EXEC=true, déconseillé)."
                ),
                "returncode": -1,
            }

        return await self._run_direct(command, timeout)

    async def _run_direct(self, command: str, timeout: int) -> dict:  # noqa: ASYNC109
        """Exécution directe V1 — sur l'hôte dans le workspace (opt-in explicite requis)."""
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._workspace,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            logger.debug("WorkerCLI exec", cmd=command[:60], rc=proc.returncode)
            return {
                "success": proc.returncode == 0,
                "stdout": stdout.decode("utf-8", errors="replace")[:8000],
                "stderr": stderr.decode("utf-8", errors="replace")[:2000],
                "returncode": proc.returncode,
            }
        except TimeoutError:
            return {
                "success": False, "stdout": "",
                "stderr": f"Timeout après {timeout}s",
                "returncode": -1,
            }
        except Exception as e:
            return {
                "success": False, "stdout": "",
                "stderr": str(e),
                "returncode": -1,
            }
