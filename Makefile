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

# stack plus the local LLM with NVIDIA acceleration (ollama profile)
up-gpu:
	docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile ollama up -d

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

# create the postgres tables (run once after the first up)
init-db:
	$(EXEC) python db.py

# rebuild the tables from scratch: ERASES the whole conversation history.
# The escape hatch for schema changes, never part of normal setup
reset-db:
	$(EXEC) python db.py --recreate

# reindex the vault: reruns the same one-shot the stack executes on up
ingest:
	docker compose run --rm ingest

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
