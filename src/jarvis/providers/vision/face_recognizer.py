# Copyright (C) 2026 Barthélemy Houot
# This file is part of Jarvis OS, licensed under the GNU AGPL-3.0-or-later.
# See the LICENSE file or <https://www.gnu.org/licenses/agpl-3.0.html>.

"""
Face recognition avec InsightFace (ArcFace, modèle buffalo_l).
Compare les frames webcam avec les visages de référence dans vision_data/faces/.

Remplace l'ancien backend dlib/face_recognition (ResNet + triplet loss, ~2017,
sujet à des faux positifs entre personnes différentes). ArcFace est l'état de
l'art open source actuel pour la reconnaissance faciale — entraîné avec une
fonction de coût spécifiquement conçue pour maximiser l'écart entre identités
différentes, nettement plus fiable en pratique.

Différence clé avec l'ancien module : dlib mesurait une DISTANCE (plus bas =
plus proche = même personne). InsightFace produit des embeddings normalisés
et on compare par SIMILARITÉ COSINUS (plus haut = plus proche = même
personne). Le seuil (FACE_RECOGNITION_THRESHOLD) a donc un sens inversé par
rapport à avant : plus la valeur est HAUTE, plus c'est strict.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field

import numpy as np
from loguru import logger

from jarvis.kernel.error_collector import collector  # jrv: autofix
from jarvis.kernel.paths import FACES_DIR  # noqa: F401
from jarvis.kernel.settings import settings


@dataclass
class RecognitionResult:
    recognized: bool  # True si un visage de référence est reconnu
    confidence: float  # 0.0-1.0 (similarité cosinus avec le meilleur match)
    name: str  # nom du fichier de référence matché, ou "unknown"
    face_locations: list = field(
        default_factory=list)  # (top, right, bottom, left), échelle 1/4


class FaceRecognizer:
    """
    Compare les frames webcam avec les visages de référence via ArcFace.
    Charge toutes les images dans vision_data/faces/ au démarrage.
    """

    # Fallback si FACE_RECOGNITION_THRESHOLD absent du .env.
    # Similarité cosinus min pour un match (plus haut = plus strict).
    RECOGNITION_THRESHOLD = 0.50
    PROCESS_EVERY_N_FRAMES = 4  # Traiter 1 frame sur 4 pour les perfs
    DET_SIZE = (320, 320)  # Résolution interne de détection (vitesse/précision)

    def __init__(self) -> None:
        self._known_embeddings: list[np.ndarray] = []
        self._known_names: list[str] = []
        self._frame_count = 0
        self._last_result: RecognitionResult | None = None
        # Seuil piloté par FACE_RECOGNITION_THRESHOLD (.env), fallback constante.
        self._threshold = settings.face_recognition_threshold or self.RECOGNITION_THRESHOLD
        self._app = None
        self._available = self._load_known_faces()

    def _init_app(self) -> bool:
        """Initialise le moteur ArcFace (téléchargement du modèle buffalo_l au
        premier lancement, ~326 Mo, mis en cache dans ~/.insightface/)."""
        try:
            from insightface.app import FaceAnalysis
        except ImportError:
            collector.warning("JRV-VIS-001", "JRV-VIS-001")
            if settings.face_recognition_enabled:
                logger.warning(
                    "FaceRecognizer: FACE_RECOGNITION_ENABLED=true mais la lib "
                    "'insightface' n'est PAS installée -> reconnaissance DESACTIVEE. "
                    "Installe : `uv pip install insightface onnxruntime` (ou l'extra "
                    "vision du projet). Sinon mets FACE_RECOGNITION_ENABLED=false "
                    "pour masquer cet avertissement."
                )
            else:
                logger.info("FaceRecognizer: lib vision absente (reconnaissance desactivee).")
            return False

        try:
            app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
            app.prepare(ctx_id=-1, det_size=self.DET_SIZE)
            self._app = app
            return True
        except Exception as e:
            collector.warning("JRV-VIS-001", "JRV-VIS-001", cause=e)
            logger.error(
                f"FaceRecognizer: échec init ArcFace (modèle non téléchargeable ? "
                f"pas de connexion internet au premier lancement ?): {e}"
            )
            return False

    def _best_face(self, faces: list) -> object | None:
        """Sélectionne le visage principal d'une image (le plus grand cadre —
        évite qu'une personne en arrière-plan ou un visage sur un poster ne
        soit pris par erreur comme sujet)."""
        if not faces:
            return None
        def _area(f: object) -> float:
            x1, y1, x2, y2 = f.bbox
            return max(0.0, x2 - x1) * max(0.0, y2 - y1)
        return max(faces, key=_area)

    def _load_known_faces(self) -> bool:
        """Charge les photos de référence. Retourne False si insightface absent."""
        if not self._init_app():
            return False

        if not FACES_DIR.exists():
            logger.warning("FaceRecognizer: dossier vision_data/faces/ absent")
            return True

        import cv2

        for img_path in FACES_DIR.glob("*.jpg"):
            name = img_path.stem
            try:
                image = cv2.imread(str(img_path))
                if image is None:
                    logger.warning(f"FaceRecognizer: image illisible {img_path}")
                    continue
                faces = self._app.get(image)
                best = self._best_face(faces)
                if best is not None:
                    self._known_embeddings.append(best.normed_embedding)
                    self._known_names.append(name)
                    logger.info(f"FaceRecognizer: chargé {name}")
                else:
                    logger.warning(
                        f"FaceRecognizer: aucun visage dans {img_path}")
            except Exception as e:
                collector.warning("JRV-VIS-001", "JRV-VIS-001", cause=e)
                logger.error(
                    f"FaceRecognizer: erreur chargement {img_path}: {e}")

        logger.info(
            f"FaceRecognizer: {len(self._known_names)} visage(s) chargé(s): "
            f"{', '.join(self._known_names) or 'aucun'}"
        )
        return True

    def process(self, frame_bgr: object, force: bool = False) -> RecognitionResult:
        """
        Analyse une frame BGR (OpenCV).
        Retourne le dernier résultat si pas le bon frame (optimisation).

        force=True : analyse systématiquement la frame, sans appliquer le
        frame-skip PROCESS_EVERY_N_FRAMES. À utiliser pour les appels discrets
        (endpoint /verify-face-frame), qui n'envoient qu'une frame.
        """
        _empty = RecognitionResult(
            recognized=False, confidence=0.0, name="unknown")

        if not self._available:
            return _empty

        self._frame_count += 1
        if not force and self._frame_count % self.PROCESS_EVERY_N_FRAMES != 0:
            return self._last_result or _empty

        if not self._known_embeddings:
            return RecognitionResult(recognized=False, confidence=0.0, name="no_reference")

        try:
            faces = self._app.get(frame_bgr)

            if not faces:
                self._last_result = RecognitionResult(
                    recognized=False, confidence=0.0, name="unknown"
                )
                return self._last_result

            best_face = self._best_face(faces)
            candidate = best_face.normed_embedding

            sims = np.array(
                [float(np.dot(known, candidate)) for known in self._known_embeddings]
            )
            best_match_idx = int(np.argmax(sims))
            best_sim = float(sims[best_match_idx])

            recognized = best_sim >= self._threshold
            best_name = self._known_names[best_match_idx] if recognized else "unknown"

            x1, y1, x2, y2 = best_face.bbox
            # Échelle 1/4 : préserve le contrat historique (dlib détectait sur
            # une frame downscalée ×0.25) — daemon.py multiplie déjà par 4.
            face_locations = [(y1 / 4, x2 / 4, y2 / 4, x1 / 4)]

            self._last_result = RecognitionResult(
                recognized=recognized,
                confidence=best_sim,
                name=best_name,
                face_locations=face_locations,
            )
            return self._last_result

        except Exception as e:
            collector.warning("JRV-VIS-001", "JRV-VIS-001", cause=e)
            logger.error(f"FaceRecognizer.process error: {e}")
            return _empty

    def add_face(self, name: str, image_path: str) -> bool:
        """Ajouter un nouveau visage de référence à chaud."""
        if not self._available:
            return False
        try:
            import cv2

            image = cv2.imread(image_path)
            if image is None:
                return False
            faces = self._app.get(image)
            best = self._best_face(faces)
            if best is not None:
                self._known_embeddings.append(best.normed_embedding)
                self._known_names.append(name)
                dest = FACES_DIR / f"{name}.jpg"
                shutil.copy(image_path, dest)
                logger.info(f"FaceRecognizer: {name} ajouté")
                return True
            return False
        except Exception as e:
            collector.warning("JRV-VIS-001", "JRV-VIS-001", cause=e)
            logger.error(f"FaceRecognizer add_face error: {e}")
            return False
