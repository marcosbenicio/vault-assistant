---
tags: [concepts, 05-monitoring]
---

# monitoring

Raw reference: the explanatory markdown of `05-monitoring/notebooks/monitoring.ipynb` (module 5 of the
course), transcribed in original order. The project notes cite
this material as the source of the concepts they apply.

---

# Folder Organization

```ymal
    05-monitoring/
    code/                        # o mini sistema (espelho do projeto final)
        rag_app/                   # pacote Python generico
        __init__.py
        ingest.py                # loader FAQ -> chunks -> Elasticsearch
        search.py                # text, vector, hybrid + rrf (vem do modulo 4)
        rag.py                   # RAGBase: retriever + llm_client + prompt
        db.py                    # init de tabelas, save conversation, save feedback
        metrics.py               # tokens, custo, latencia
        app.py                   # Streamlit UI
        generate_data.py           # trafego sintetico pra popular o dashboard
        pyproject.toml
        Makefile                   # make ingest / make app / make init-db
    grafana/
        dashboards/main.json       # dashboard versionado
        provisioning/              # datasource Postgres + auto-load do json
    notebooks/
        monitoring.ipynb           # anotações das aulas, teoria, experimentos
    homework/
```
The course keeps the module 5 code as sixteen flat scripts in a single folder. I follow the same flat style inside rag-app, but with fewer files: the four db_* scripts of the course become functions in a single db.py, and the course dashboard.py is skipped entirely because later lessons replace it with Grafana reading from Postgres. This layout mirrors the fitness-assistant project example from module 7, so at the end of the module the folder doubles as the skeleton of my final project. 

The infrastructure also differs from the course: instead of its docker-compose, I reuse my own stack, which already runs Elasticsearch and Postgres, and will only need a Grafana service added when the dashboard lessons arrive.

# Assistant Setup

The lesson builds a command line RAG assistant out of three flat files in code/rag-app, shown below in the order they stack: base_rag.py defines the generic RAG class, ingest.py loads the data it searches over, and assistant.py wires the two together.

My setup differs from the lesson in two ways. The course runs everything on the host with uv, but my Python environment lives inside the notebook container, so the Makefile run target first makes sure the container is up and then executes the script inside it with docker compose exec. The course also loads the API key from a local .env file with python-dotenv, which in my case is redundant because the compose file already injects OPENAI_API_KEY into the container environment.

base_rag.py carries the RAGBase class from module 3. It holds the whole RAG loop: search queries the minsearch index with field boosts and a course filter, build_context and build_prompt turn the retrieved documents into a single prompt, llm sends it to gpt-5.4-mini through the Responses API with instructions to answer only from the context, and rag chains the three steps.


**base_rag.py**


```python
INSTRUCTIONS = '''
Your task is to answer questions from the course participants
based on the provided context.

Use the context to find relevant information and provide accurate
answers. If the answer is not found in the context,
respond with "I don't know."
'''

PROMPT_TEMPLATE = '''
QUESTION: {question}

CONTEXT:
{context}
'''.strip()


class RAGBase:

    def __init__(
        self,
        index,
        llm_client,
        instructions=INSTRUCTIONS,
        prompt_template=PROMPT_TEMPLATE,
        course='llm-zoomcamp',
        model='gpt-5.4-mini'
    ):
        self.index = index
        self.llm_client = llm_client
        self.instructions = instructions
        self.course = course
        self.prompt_template = prompt_template
        self.model = model

    def search(self, query, num_results=5):
        boost_dict = {'question': 3.0, 'section': 0.5}
        filter_dict = {'course': self.course}

        return self.index.search(
            query,
            num_results=num_results,
            boost_dict=boost_dict,
            filter_dict=filter_dict
        )

    def build_context(self, search_results):
        lines = []

        for doc in search_results:
            lines.append(doc['section'])
            lines.append('Q: ' + doc['question'])
            lines.append('A: ' + doc['answer'])
            lines.append('')

        return '\n'.join(lines).strip()

    def build_prompt(self, query, search_results):
        context = self.build_context(search_results)
        return self.prompt_template.format(
            question=query, context=context
        )

    def llm(self, prompt):
        input_messages = [
            {'role': 'developer', 'content': self.instructions},
            {'role': 'user', 'content': prompt}
        ]

        response = self.llm_client.responses.create(
            model=self.model,
            input=input_messages
        )

        return response.output_text

    def rag(self, query):
        search_results = self.search(query)
        prompt = self.build_prompt(query, search_results)
        answer = self.llm(prompt)
        return answer
```

ingest.py is the data layer. load_faq_data downloads the FAQ documents for all courses from datatalks.club, and build_index fits a minsearch Index over the question, section and answer text fields, keeping course as a keyword field for filtering.


**ingest.py**

```python
import requests
from minsearch import Index


def load_faq_data():
    docs_url = 'https://datatalks.club/faq/json/courses.json'
    response = requests.get(docs_url)
    courses_raw = response.json()

    documents = []
    url_prefix = 'https://datatalks.club/faq'

    for course in courses_raw:
        course_url = f'{url_prefix}{course["path"]}'
        course_response = requests.get(course_url)
        course_response.raise_for_status()
        course_data = course_response.json()

        documents.extend(course_data)

    return documents


def build_index(documents):
    index = Index(
        text_fields=['question', 'section', 'answer'],
        keyword_fields=['course']
    )
    index.fit(documents)
    return index


```

assistant.py is the entry point. create_assistant loads the documents, builds the index and returns a RAGBase instance connected to the OpenAI client. Run as a script, it answers a default question or any question passed as a command line argument.


**assistant.py**

```python
import sys

from dotenv import load_dotenv
from openai import OpenAI

from ingest import load_faq_data, build_index
from base_rag import RAGBase


def create_assistant():
    load_dotenv("/workspace/.env")

    documents = load_faq_data()
    index = build_index(documents)

    return RAGBase(
        index=index,
        llm_client=OpenAI(),
    )
    

if __name__ == "__main__":
    assistant = create_assistant()

    query = "How do I join the course?"
    if len(sys.argv) > 1:
        query = sys.argv[1]

    answer = assistant.rag(query)
    print(answer)
```

The Makefile automates the run from the host. The COMPOSE variable points to my compose file four levels up, and the run target first guarantees the notebook container is running, then executes assistant.py inside it, in the right working directory.

```makefile
COMPOSE = docker compose -f ../../../../docker-compose.yml
WORKDIR = /workspace/llm-zoomcamp-2026/05-monitoring/code/rag-app

run:
	$(COMPOSE) up -d notebook
	$(COMPOSE) exec --workdir $(WORKDIR) notebook python assistant.py
```


 The output below shows the full round trip: make run starts the stack, downloads and indexes the FAQ, retrieves the top documents for the question and generates the answer.

```bash
    (base) marcos@HAI-LP-004:~/studies/llm-zoomcamp-2026/05-monitoring/code/rag-app$ make run
    docker compose -f ../../../../docker-compose.yml up -d notebook
    [+] up 3/3
    ✔ Container pgvector      Running                                                                                                                                                      0.0s
    ✔ Container elasticsearch Running                                                                                                                                                      0.0s
    ✔ Container studies       Running                                                                                                                                                      0.0s
    docker compose -f ../../../../docker-compose.yml exec --workdir /workspace/llm-zoomcamp-2026/05-monitoring/code/rag-app notebook python assistant.py
    Yes, you can join the course even if you just discovered it.

    Start with the course docs and repository:
    - [LLM Zoomcamp docs](https://datatalks.club/docs/courses/llm-zoomcamp/)
    - [General Zoomcamp logistics](https://datatalks.club/docs/courses/zoomcamp-logistics/)
    - [LLM Zoomcamp GitHub repo](https://github.com/DataTalksClub/llm-zoomcamp)

    You can begin anytime, but if you want a certificate, you must submit your project while submissions are still open.

```

# Chat App

app.py builds the interface. It imports create_assistant from assistant.py, shows a text input and a button, and on click runs the full RAG loop inside a spinner. My one deviation from the lesson is the st.cache_resource decorator: without it, the rerun model of Streamlit would download and reindex the whole FAQ on every interaction. The decorator creates the assistant once and reuses it across reruns, which is also mandatory in the final project, where rebuilding the index means rereading the whole Obsidian vault.



```python
import streamlit as st
from assistant import create_assistant


@st.cache_resource
def get_assistant():
    return create_assistant()


assistant = get_assistant()

st.title("Course Assistant")

user_input = st.text_input("Enter your question:")

if st.button("Ask"):
    with st.spinner("Processing..."):
        answer = assistant.rag(user_input)
        st.success("Completed!")
        st.write(answer)
```

The chat target runs the app inside the container. The server.address flag makes Streamlit listen on all interfaces of the container, otherwise the published port would never reach it. The app becomes available at localhost:8501.

The Makefile grows a second target and gains variables to avoid repetition. COMPOSE points to my compose file four levels up, WORKDIR is where this module's code lives inside the container, and EXEC combines both into the full command that executes something in the right folder of the running container. Each target then reads as intent: run answers a question from the command line, chat serves the web app.

Both targets start with up -d notebook, which is a cheap safety net: if the container is already running it does nothing, if not it brings it up, so make never fails because the stack was down.

The chat target needs two flags that the lesson does not. Streamlit by default listens only on localhost, which inside a container means the container's own loopback, unreachable from outside. The server.address flag makes it listen on all interfaces, so the published port 8501 actually reaches it. The server.headless flag stops Streamlit from asking for an email and trying to open a browser, neither of which makes sense inside a container. After make chat, the app is available at localhost:8501 on the host.



```makefile
COMPOSE = docker compose -f ../../../../docker-compose.yml
WORKDIR = /workspace/llm-zoomcamp-2026/05-monitoring/code/rag-app
EXEC = $(COMPOSE) exec --workdir $(WORKDIR) notebook

run:
	$(COMPOSE) up -d notebook
	$(EXEC) python assistant.py

chat:
	$(COMPOSE) up -d notebook
	$(EXEC) streamlit run app.py --server.address 0.0.0.0 --server.headless true
```

Expected output

```bash
(base) marcos@HAI-LP-004:~/studies/llm-zoomcamp-2026/05-monitoring/code/rag-app$ make chat
docker compose -f ../../../../docker-compose.yml up -d notebook
[+] up 3/3
 ✔ Container pgvector      Running                                                                                                                                                      0.0s
 ✔ Container elasticsearch Running                                                                                                                                                      0.0s
 ✔ Container studies       Running                                                                                                                                                      0.0s
docker compose -f ../../../../docker-compose.yml exec --workdir /workspace/llm-zoomcamp-2026/05-monitoring/code/rag-app notebook streamlit run app.py --server.address 0.0.0.0 --server.headless true

Collecting usage statistics. To deactivate, set browser.gatherUsageStats to false.

2026-07-14 21:08:17.887 Uvicorn server started on 0.0.0.0:8501

  You can now view your Streamlit app in your browser.

  Local URL: http://localhost:8501
  Network URL: http://172.19.0.6:8501
  External URL: http://191.199.218.40:8501

  Detected WSL. Using poll-based file watching for better compatibility. To force watchdog, set server.fileWatcherType = "watchdog".
```

# Capturing Metrics

The lesson starts the actual monitoring: every LLM call should leave a record of how long it took, how many tokens it consumed and how much it cost. Nothing changes in the infrastructure and nothing changes in the RAG logic. A new metrics.py subclasses RAGBase and overrides only the method that talks to the LLM. The record stays in memory for now; persisting it to Postgres is the next lesson.

I deviate from the course in one detail. The lesson creates the timestamp with a naive datetime.now and only fixes it in the database lesson, because Grafana misaligns the time axis when timestamps carry no timezone. My record is born timezone aware with datetime.now().astimezone().

metrics.py is the instrumentation layer. LLMCallRecord is a dataclass that bundles everything one call produces: model, prompt, instructions, answer, token counts, elapsed time, cost and a timestamp. calculate_cost prices the call with the gpt-5.4-mini rates as the lesson recorded them, 0.15 dollars per million input tokens and 0.60 per million output tokens, returning zero for any other model. (Those lesson rates are outdated: the current pricing page lists gpt-5.4-mini at 0.75 in and 4.50 out, and the project's own metrics.py uses the correct table — see the gpt_pricing note.) RAGWithMetrics extends RAGBase and touches only the LLM step. The original llm method returned just the answer text, which throws away the usage information that comes in the response, so the subclass splits it in three: _call_llm makes the request and returns the full response object, _log_response turns the response and the elapsed time into an LLMCallRecord kept in last_call, and llm itself only starts the clock and delegates. Search, context and prompt building are inherited untouched, so the rest of the pipeline never notices it is being measured.

**metrics.py**

```python
import time
from dataclasses import dataclass, field
from datetime import datetime

from base_rag import RAGBase


@dataclass
class LLMCallRecord:
    model: str
    prompt: str
    instructions: str
    answer: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    response_time: float
    cost: float
    timestamp: datetime = field(
        default_factory=lambda: datetime.now().astimezone()
    )


def calculate_cost(model, usage):
    cost = 0
    if "gpt-5.4-mini" in model:
        cost = (usage.input_tokens * 0.15 + usage.output_tokens * 0.60) / 1_000_000
    return cost


class RAGWithMetrics(RAGBase):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_call: LLMCallRecord = None

    def llm(self, prompt):
        start_time = time.time()
        response = self._call_llm(prompt)
        response_time = time.time() - start_time
        self._log_response(prompt, response, response_time)
        return response.output_text

    def _call_llm(self, prompt):
        input_messages = [
            {"role": "developer", "content": self.instructions},
            {"role": "user", "content": prompt}
        ]
        response = self.llm_client.responses.create(
            model=self.model,
            input=input_messages
        )
        return response

    def _log_response(self, prompt, response, response_time):
        usage = response.usage
        cost = calculate_cost(self.model, usage)

        call_record = LLMCallRecord(
            model=self.model,
            prompt=prompt,
            instructions=self.instructions,
            answer=response.output_text,
            prompt_tokens=usage.input_tokens,
            completion_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            response_time=response_time,
            cost=cost,
        )

        print(call_record)
        self.last_call = call_record
```

assistant.py changes one line of substance: create_assistant now returns RAGWithMetrics instead of RAGBase, so both entry points, the CLI and the web app, start recording metrics without any other change.

**assistant.py**

```python
import sys

from dotenv import load_dotenv
from openai import OpenAI

from ingest import load_faq_data, build_index
from metrics import RAGWithMetrics


def create_assistant():
    load_dotenv("/workspace/.env")

    documents = load_faq_data()
    index = build_index(documents)

    return RAGWithMetrics(
        index=index,
        llm_client=OpenAI(),
    )


if __name__ == "__main__":
    assistant = create_assistant()

    query = "How do I join the course?"
    if len(sys.argv) > 1:
        query = sys.argv[1]

    answer = assistant.rag(query)
    print(answer)
```

app.py reads the record of the call it just made and prints the numbers under the answer. The record comes from assistant.last_call, which always holds the most recent call, so the interface now shows what each question costs as soon as it is answered.

**app.py**

```python
import streamlit as st
from assistant import create_assistant


@st.cache_resource
def get_assistant():
    return create_assistant()


assistant = get_assistant()

st.title("Course Assistant")

user_input = st.text_input("Enter your question:")

if st.button("Ask"):
    with st.spinner("Processing..."):
        answer = assistant.rag(user_input)
        st.success("Completed!")
        st.write(answer)

        record = assistant.last_call
        st.write(f"Response time: {record.response_time:.2f}s")
        st.write(f"Prompt tokens: {record.prompt_tokens}")
        st.write(f"Completion tokens: {record.completion_tokens}")
        st.write(f"Cost: ${record.cost:.4f}")
```

# Storing Data in PostgreSQL

The lesson makes the metrics survive: every call record now goes into a PostgreSQL table instead of dying with the process. The course spends half of it on infrastructure, creating a Docker network called monitoring and starting a postgres:17 container by hand with docker run, so that Grafana can later reach the database by name. I skip all of that because my compose stack already runs Postgres and Grafana on the same network. The only setup left is creating a dedicated database inside the existing instance, once:

```bash
docker compose exec pgvector psql -U user -d faq -c "CREATE DATABASE course_assistant;"
```

One Postgres instance can hold many isolated databases, so the faq database of module 2 and the course_assistant database of this module live side by side in the same container without touching each other.

Instead of the course's docker run, the database is the pgvector service that already lives in my compose file. The excerpt below shows the only parts that matter for this lesson. The image is a stock Postgres 18 with the vector extension baked in. On first start it creates the faq database used in module 2, and the course_assistant database of this module was created inside the same instance with the command above, since one Postgres can hold many isolated databases. Port 5432 is published so psql works from the host, and the data lives in a named volume, so the container can be recreated without losing anything. The only Postgres 18 detail is the volume path: it mounts the parent /var/lib/postgresql, while the postgres:17 of the course mounts the /data subdirectory.

The connection info travels as environment variables injected into the notebook container, where the code runs. POSTGRES_HOST is just the service name: containers on the same Docker network, llm-net here, resolve each other by name, which is also how Grafana will reach the database in the dashboard lessons. This shared network replaces the docker network create monitoring step of the course.

```yaml
# excerpt from my docker-compose.yml

  pgvector:
    image: pgvector/pgvector:pg18
    container_name: pgvector
    restart: unless-stopped
    environment:
      POSTGRES_DB: faq              # default database, created on first start
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pswd
    ports:
      - "5432:5432"                 # psql access from the host
    volumes:
      - pgvector_data:/var/lib/postgresql   # pg18 mounts the parent dir,
                                            # postgres:17 used /data
    networks:
      - llm-net

  notebook:
    environment:
      POSTGRES_HOST: "pgvector"     # service name = hostname on llm-net
      POSTGRES_USER: "user"
      POSTGRES_PASSWORD: "pswd"
```

db.py is the persistence layer, fusing the course's db_init.py and db_save.py into one file. get_db_connection reads host and credentials from the environment but hardcodes the database name: the container injects POSTGRES_DB=faq for module 2, and reading it here would silently create the monitoring tables in the wrong database. init_db creates the conversations table, one row per LLM call, mirroring the fields of LLMCallRecord plus the question and the course; the timestamp column is TIMESTAMP WITH TIME ZONE, the detail Grafana depends on to align the time axis. save_conversation inserts a record and returns the id that RETURNING id hands back, useless today but the hook where lesson 08 attaches user feedback. I also deviate from the course by storing record.timestamp, taken when the call happened, instead of generating a fresh timestamp at save time, which is what the course's DB_TIMEZONE machinery does.

**db.py**

```python
import os

import psycopg


def get_db_connection():
    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        dbname="course_assistant",
        user=os.getenv("POSTGRES_USER", "user"),
        password=os.getenv("POSTGRES_PASSWORD", "pswd"),
    )


def init_db(drop=False):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if drop:
                cur.execute("DROP TABLE IF EXISTS conversations")

            cur.execute("""
                CREATE TABLE conversations (
                    id SERIAL PRIMARY KEY,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    course TEXT NOT NULL,
                    model TEXT NOT NULL,
                    instructions TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    total_tokens INTEGER NOT NULL,
                    response_time FLOAT NOT NULL,
                    cost FLOAT NOT NULL,
                    timestamp TIMESTAMP WITH TIME ZONE NOT NULL
                )
            """)
        conn.commit()
    finally:
        conn.close()


def save_conversation(record, question, course):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversations (
                    question, answer, course, model, instructions, prompt,
                    prompt_tokens, completion_tokens, total_tokens,
                    response_time, cost, timestamp
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING id
                """,
                (
                    question,
                    record.answer,
                    course,
                    record.model,
                    record.instructions,
                    record.prompt,
                    record.prompt_tokens,
                    record.completion_tokens,
                    record.total_tokens,
                    record.response_time,
                    record.cost,
                    record.timestamp,
                ),
            )
            conversation_id = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    return conversation_id


if __name__ == "__main__":
    init_db()
    print("Database initialized")
```

assistant.py gains one import and one line: after answering on the command line, it saves the call record with the question and the course id. Nothing else changes.

**assistant.py**

```python
import sys

from dotenv import load_dotenv
from openai import OpenAI

from ingest import load_faq_data, build_index
from metrics import RAGWithMetrics
from db import save_conversation


def create_assistant():
    load_dotenv("/workspace/.env")

    documents = load_faq_data()
    index = build_index(documents)

    return RAGWithMetrics(
        index=index,
        llm_client=OpenAI(),
    )


if __name__ == "__main__":
    assistant = create_assistant()

    query = "How do I join the course?"
    if len(sys.argv) > 1:
        query = sys.argv[1]

    answer = assistant.rag(query)
    print(answer)

    save_conversation(assistant.last_call, query, "llm-zoomcamp")
```

app.py saves right after showing the metrics, with one Streamlit twist: the returned conversation_id goes into st.session_state, the dictionary that survives the reruns of the script, so the feedback buttons of lesson 08 can attach a thumbs up or down to the conversation that was just answered.

**app.py**

```python
import streamlit as st
from assistant import create_assistant
from db import save_conversation


@st.cache_resource
def get_assistant():
    return create_assistant()


assistant = get_assistant()

st.title("Course Assistant")

user_input = st.text_input("Enter your question:")

if st.button("Ask"):
    with st.spinner("Processing..."):
        answer = assistant.rag(user_input)
        st.success("Completed!")
        st.write(answer)

        record = assistant.last_call
        st.write(f"Response time: {record.response_time:.2f}s")
        st.write(f"Prompt tokens: {record.prompt_tokens}")
        st.write(f"Completion tokens: {record.completion_tokens}")
        st.write(f"Cost: ${record.cost:.4f}")

        conversation_id = save_conversation(record, user_input, "llm-zoomcamp")
        st.session_state.conversation_id = conversation_id
```

The Makefile closes the lesson with three database targets, and they follow the three layers of Postgres. The server is the pgvector container, long running in the compose stack. Inside the server live databases: faq was born with the container, defined by POSTGRES_DB in the compose file, and course_assistant has to be created once. Inside the database live tables, and that is where conversations goes.

create-db handles the middle layer. It cannot be done from db.py, because psycopg needs to connect to some database before executing anything, and the one it wants to connect to is exactly the one that does not exist yet. So the database is created through psql, connecting to faq, which already exists. The course never hits this because its container is born with POSTGRES_DB=course_assistant; mine was born with faq, so the second database enters by hand. In the final project this target disappears: the project will have its own compose file whose Postgres service is born with the right database, so setup reduces to docker compose up followed by make init-db.

init-db handles the last layer: it runs db.py as a script, whose main block calls init_db and creates the conversations table. Once is enough for the life of the database, since the table lives in the Postgres volume, not in the container. Running it again fails with relation already exists, which is just Postgres saying the work is done; in the final project init_db will use CREATE TABLE IF NOT EXISTS instead, making the target idempotent. The drop=True flag of init_db deletes the table with all collected data, so no target ever calls it, only by hand and on purpose.

check-db only reads: it runs a SELECT straight in the Postgres container to show what is stored. Note that create-db and check-db use \$(COMPOSE) exec pgvector instead of \$(EXEC), because they run in the database container, needing neither the working directory nor the Python environment of the notebook one. Keeping everything as targets means the whole workflow stays in the Makefile, which is also how the final project will document itself: anyone cloning the repo reads the targets and knows every command.

```makefile
database:
	$(COMPOSE) exec pgvector psql -U user -d faq \
		-c "CREATE DATABASE course_assistant;"

init-db:
	$(EXEC) python db.py

check-db:
	$(COMPOSE) exec pgvector psql -U user -d course_assistant \
		-c "SELECT id, question, cost, timestamp FROM conversations;"
```

The loop then closes in four steps, all from the rag-app folder: make create-db once, make init-db once, make run to answer and save one conversation, and make check-db to see it as a row. If the question shows up with a cost and a timezone aware timestamp, the path from app to Postgres works end to end.

Running the whole loop, in order and from the rag-app folder:

```bash
make create-db    # creates the course_assistant database, once
make init-db      # creates the conversations table, once
make chat         # serves the app at localhost:8501
```

With the app up, every question answered through the interface is persisted by save_conversation. After two questions in the chat, check-db already tells the story:

```bash
(base) marcos@HAI-LP-004:~/studies/llm-zoomcamp-2026/05-monitoring/code/rag-app$ make check-db
docker compose -f ../../../../docker-compose.yml exec pgvector psql -U user -d course_assistant \
        -c "SELECT id, question, cost, timestamp FROM conversations;"
 id |          question          |          cost          |           timestamp
----+----------------------------+------------------------+-------------------------------
  1 | How do I join the course?  |             0.00017925 | 2026-07-14 21:59:53.324785+00
  2 | how can i take certificate | 0.00010530000000000001 | 2026-07-14 22:01:29.039757+00
(2 rows)
```

Each row is one LLM call with its cost and a timezone aware timestamp, which Postgres stores normalized to UTC, the +00 suffix. The path from the browser to the database is closed; the next lessons read this table back, first from Python, then from Grafana.

# Querying Data

The lesson adds the read path: the conversations stored by the app come back into Python, ready for the Streamlit dashboard of the next lesson, which consumes these functions. No new infrastructure and no new library. In the course this is a fourth file, db_query.py; in my layout the functions join db.py, which now holds the full life cycle of the data in one place: init_db creates the table, save_conversation writes to it, get_conversations reads it back.

db.py gains the read side: row_to_record and get_conversations, plus the import of LLMCallRecord at the top of the file. psycopg returns each row as a positional tuple, so row_to_record converts it back into the LLMCallRecord dataclass and the rest of the code keeps working with named fields instead of magic indexes. The indexes follow the exact column order of the SELECT: 0 is id, 1 question, 2 answer, 3 course, 4 model, 5 instructions, 6 prompt, 7 to 9 the token counts, 10 response_time, 11 cost and 12 timestamp. id, question and course have no field in the dataclass, which explains the gaps in the mapping.

get_conversations brings the most recent conversations first. The lesson itself points out the limitation: there is no index on timestamp, only on id from the primary key, and since ids grow with time, ordering by id would be faster on a large table. Irrelevant at this volume, worth remembering in the final project.

**db.py additions**

```python
from metrics import LLMCallRecord


def row_to_record(row):
    return LLMCallRecord(
        model=row[4],
        prompt=row[6],
        instructions=row[5],
        answer=row[2],
        prompt_tokens=row[7],
        completion_tokens=row[8],
        total_tokens=row[9],
        response_time=row[10],
        cost=row[11],
        timestamp=row[12],
    )


def get_conversations(limit=10):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, question, answer, course, model,
                       instructions, prompt,
                       prompt_tokens, completion_tokens, total_tokens,
                       response_time, cost, timestamp
                FROM conversations
                ORDER BY timestamp DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return [row_to_record(row) for row in rows]
```

The course tests this by running python db_query.py as a script; my db.py main block already belongs to init_db, so the smoke test becomes a Makefile target that imports the function and prints. make query-db shows the stored records as LLMCallRecord objects, most recent first, closing the loop in both directions: the app writes through save_conversation and anything can read back through get_conversations.

```makefile
query-db:
	$(EXEC) python -c "from db import get_conversations; \
		[print(r.timestamp, r.model, f'{r.cost:.6f}', repr(r.answer[:60])) for r in get_conversations()]"

```
