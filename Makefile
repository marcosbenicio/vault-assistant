# All targets run against this folder's compose stack. The app and notebook
# services share one image; code is bind-mounted, so edits apply live.

EXEC = docker compose exec --workdir /app app

# start the whole stack, local llm included (what a fresh clone runs;
# the first start pulls the ollama image and a basic local model)
up:
	docker compose up -d

# rebuild the image and start: only needed when requirements.txt changes
build:
	docker compose up -d --build

# stop and remove the containers; data survives in the named volumes
down:
	docker compose down

# stack with NVIDIA acceleration for the local models (one-off; the
# persistent way is: cp docker-compose.gpu.yml docker-compose.override.yml)
up-gpu:
	docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d

# apply .env changes to the notebook service; kills the Jupyter kernel,
# save first. A recreate is required: restart does not reread .env
reload-notebook:
	docker compose up -d --force-recreate notebook

# apply .env changes to the app; just a quick Streamlit blink
reload-app:
	docker compose up -d --force-recreate app

# switch the app's color palette (saved themes live in
# assistant/.streamlit/themes/; add a toml there to add a palette)
theme-kimbie:
	cp assistant/.streamlit/themes/kimbie.toml assistant/.streamlit/config.toml
	docker compose restart app
theme-friedrich:
	cp assistant/.streamlit/themes/friedrich.toml assistant/.streamlit/config.toml
	docker compose restart app
theme-default:
	rm -f assistant/.streamlit/config.toml
	docker compose restart app

# create the postgres tables by hand (the app already runs this on its
# own startup; kept as the manual echo)
init-db:
	$(EXEC) python db.py

# rebuild the tables from scratch: ERASES the whole conversation history.
# The escape hatch for schema changes, never part of normal setup
reset-db:
	$(EXEC) python db.py --recreate

# reindex the vault: reruns the same one-shot the stack executes on up
ingest:
	docker compose run --rm ingest

# point the stack at your own vault in one command: writes VAULT_PATH
# into .env, reindexes your notes and recreates the app with the new
# mount. Usage:
#   make vault VAULT=/abs/path/to/your/notes    (on WSL, C:\ is /mnt/c/)
#   make vault VAULT=demo                       (back to the demo vault)
vault:
	@test -n "$(VAULT)" || { echo "usage: make vault VAULT=/abs/path/to/your/notes (or VAULT=demo)"; exit 1; }
	@if [ "$(VAULT)" = "demo" ]; then \
		sed -i '/^VAULT_PATH=/d' .env; \
		echo "vault: back to the demo"; \
	else \
		test -d "$(VAULT)" || { echo "not a directory: $(VAULT)"; exit 1; }; \
		sed -i '/^VAULT_PATH=/d' .env; \
		printf 'VAULT_PATH=%s\n' "$(VAULT)" >> .env; \
		echo "vault: $(VAULT)"; \
	fi
	docker compose run --rm ingest
	docker compose up -d --force-recreate app

# peek at the last 10 logged conversations in postgres (the container's
# own POSTGRES_USER is used, so .env overrides keep working)
check-db:
	docker compose exec postgres sh -c 'psql -U $$POSTGRES_USER -d obsidian_assistant \
		-c "SELECT id, question, model, cost, response_time, created_at FROM conversations ORDER BY id DESC LIMIT 10;"'

# follow the app logs live (ctrl+c to leave)
logs:
	docker compose logs -f app

# print every service address, honoring the port overrides in .env
urls:
	@. ./.env 2>/dev/null || true; \
	echo "App:      http://localhost:$${APP_PORT:-8501}"; \
	echo "Jupyter:  http://localhost:$${JUPYTER_PORT:-8888}/?token=$${JUPYTER_TOKEN:-dev}"; \
	echo "Grafana:  http://localhost:$${GRAFANA_PORT:-3000}  (admin / $${GRAFANA_PASSWORD:-admin})"; \
	echo "Elastic:  http://localhost:$${ES_PORT:-9200}"
