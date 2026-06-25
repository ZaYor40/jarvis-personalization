FROM python:3.11-slim

# Deps système minimales : portaudio19-dev pour pyaudio (transitif RealtimeSTT,
# pas de wheel linux, compile depuis sdist). python3-dev requis pour la compilation.
# opencv-python et dlib (vision, non installé ici) ont des wheels linux x86_64
# prêtes — pas besoin de cmake/openblas/libgl1 (cf. lane CI minimum du repo).
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    portaudio19-dev \
    gcc \
    python3-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# uv installé en standalone (pas de dépendance à un paquet apt)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Copie du lockfile + pyproject d'abord pour profiter du cache Docker
# sur les layers de dépendances (ne re-sync que si ces fichiers changent)
COPY pyproject.toml uv.lock ./

# Sync des deps de base uniquement (pas vision, pas dev) — cf. décision
# "API texte + vocal Cloud" : pas de face-recognition pour l'instant
RUN uv sync --frozen --no-install-project

# Copie du reste du code applicatif
COPY . .

# Sync final pour installer le package jarvis lui-même
RUN uv sync --frozen --no-extra vision --no-group dev

# Arborescence attendue par l'app (cf. setup.sh --ci)
RUN mkdir -p memory_data/sessions \
             memory_data/topics \
             memory_data/conso \
             memory_data/initiatives \
             memory_data/curator_reports \
             skills_data/installed \
             skills_data/candidates \
             workspace/projects

EXPOSE 8000

# API + voice agent (LiveKit Cloud, pas de serveur LiveKit local lancé ici —
# cf. décision : jarvis run lance livekit-server --dev inconditionnellement,
# on ne veut pas ça puisqu'on utilise LiveKit Cloud)
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
