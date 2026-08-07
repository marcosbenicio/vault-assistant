# All targets run against this folder's compose stack. The app and notebook
# services share one image; code is bind-mounted, so edits apply live.

EXEC = docker compose exec --workdir /app app

# start the whole stack, API-only default (what a fresh clone runs)
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

# create the postgres tables (run once after the first up)
init-db:
	$(EXEC) python db.py

# rebuild the tables from scratch: ERASES the whole conversation history.
# The escape hatch for schema changes, never part of normal setup
reset-db:
	$(EXEC) python db.py --recreate

# ingest the vault into elasticsearch from the terminal
ingest:
	$(EXEC) python ingest.py

# peek at the last 10 logged conversations in postgres
check-db:
	docker compose exec postgres psql -U user -d obsidian_assistant \
		-c "SELECT id, question, model, cost, response_time, created_at FROM conversations ORDER BY id DESC LIMIT 10;"

# follow the app logs live (ctrl+c to leave)
logs:
	docker compose logs -f app

# print every service address
urls:
	@echo "App:      http://localhost:8501"
	@echo "Jupyter:  http://localhost:8888/?token=$${JUPYTER_TOKEN:-dev}"
	@echo "Grafana:  http://localhost:3000  (admin / admin)"
	@echo "Elastic:  http://localhost:9200"
