.PHONY: boot run voice livekit start

start:
	@echo "Démarrage Jarvis (LiveKit + API + Voice)..."
	@trap 'kill $$(jobs -p) 2>/dev/null; exit 0' INT TERM; \
	livekit-server --dev --node-ip 127.0.0.1 --keys "devkey: devsecretdevsecretdevsecretdevsecret" & \
	sleep 2 && uv run python -m jarvis.app & \
	sleep 4 && uv run python -m jarvis.interfaces.voice.agent dev; \
	wait

invoque:
	@bash setup.sh

run:
	@uv run python -m jarvis.app

livekit:
	@echo "Démarrage LiveKit local sur ws://localhost:7880"
	@livekit-server --dev --node-ip 127.0.0.1 --keys "devkey: devsecretdevsecretdevsecretdevsecret"

voice:
	@uv run python -m jarvis.interfaces.voice.agent dev
