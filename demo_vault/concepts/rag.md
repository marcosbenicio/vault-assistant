---
tags: [concepts, 01-agentic-rag]
---

# rag

Raw reference: the explanatory markdown of `01-agentic-rag/notebooks/rag.ipynb` (module 1 of the
course), transcribed in original order. The project notes cite
this material as the source of the concepts they apply.

---

# Setup

# Data Ingestion

Pull the course FAQ data from DataTalks.Club's public endpoint. The data is organized in two steps:

1. **Index of courses**: `https://datatalks.club/faq/json/courses.json` returns a list of available courses, each with a `path`.
2. **Per-course FAQ**: for each course, we fetch its FAQ JSON from `https://datatalks.club/faq{path}`, which gives us a list of entries.

Each FAQ entry follows the same schema:

| Field | Meaning |
|---|---|
| `question` | the student's question |
| `answer` | the answer text |
| `section` | the module/topic the question belongs to |
| `course` | which course it came from (e.g. `llm-zoomcamp`, `data-engineering-zoomcamp`) |

To compare documents mathematically, we use the library minsearch to represent them as numeric vectors. The bag-of-words approach builds a term-document matrix where each row is a document and each column is a word in the vocabulary. Word order is ignored and most entries are zero (so the matrix is sparse).

The minsearch uses `CountVectorizer` to simply counts how many times each word appears in the document. Also uses the `TfidfVectorizer` to  reweights the counts by the rarity of each word in the corpus. The idea is that words like "the" and "is" appear in almost every document and don't help distinguish one from another, while words like "docker" or "python" are discriminative.

The weight of a term $t$ in a document $d$ is given by:

$$
\text{TF-IDF}(t, d) = \underbrace{f(t, d)}_{\text{frequency of } t \text{ in } d} \times \underbrace{\log \frac{N}{n_t}}_{\text{inverse document frequency}}
$$

where $N$ is the total number of documents and $n_t$ is the number of documents that contain the term $t$. The parameter `stop_words='english'` removes common words before vectorization, and `min_df=5` ignores words appearing in fewer than 5 documents. The `minsearch.Index` we use here is a thin wrapper over `TfidfVectorizer`: each field declared in `text_fields` gets its own TfidfVectorizer (so question and answer live in separate TF-IDF spaces), and at search time the query is vectorized per field, scored by cosine similarity, weighted by the optional boost_dict, and summed into a final relevance score. The fields declared as `keyword_fields` are not vectorized, they are stored as exact strings and used only for filtering (for example, restricting a search to a single course).


This is conceptually close to what we will later see with embeddings: in both cases we map text to a vector and compare with cosine similarity. The difference is what each dimension means. In TF-IDF every dimension corresponds to one word of the vocabulary, so synonyms like "car" and "automobile" end up in different dimensions and are seen as unrelated. Embeddings, on the other hand, are dense vectors of learned features trained on millions of texts, so synonyms and paraphrases end up close together. TF-IDF is stronger when exact technical terms matter; embeddings are stronger for paraphrases and natural-language queries. Production systems usually combine both in a hybrid search. For this notebook we stick with `minsearch` because it requires no infrastructure and lets us see the whole pipeline — vectorize, score by cosine, return top-k — without any model downloads.

# RAG

# Call the RAG assistant

This approach has a limitation: it only works for questions that can be answered with the information in the documents. If the question is outside the scope of the documents, the assistant will not be able to provide a useful answer. Even when the answer isn't in our data, the model still receives 5 irrelevant docs and has to say "I don't know".

# Function Calling

Instead of forcing a search for every question, we can use function calling to let the model decide when to search and when to answer directly. This is called an agentic loop. This way a model that thinks, acts (call tools), observes (read the results), and repeats until it's ready to answer.

With `tools=[search_tool]`, the model decided to call `search` and even reformulated the natural question into search-friendly keywords (`"join course discovered late enrollment eligibility"`). Without the tool, the model answered directly, but the answer is vague and hedged (*"usually... it depends..."*) and even drifts off-topic (offering to draft a message to the registrar) 

 Note also that the function-calling version didn't finish: the model only emitted a tool call, never a final answer. To actually get a response we still need to execute the tool, feed the results back, and let the model decide again. That loop is what turns a single function call into a agentic flow.

the response we got back from the LLM is not an answer to the user, it is a request to use a function. When we expose `tools=[search_tool]`, the model can decide that the best next move is to call the tool instead of replying directly. In that case, the first element of `response.output` is a `ResponseFunctionToolCall`, which carries the function name, a `call_id`, and a string of JSON arguments. The LLM itself does not execute anything: it only describes, in JSON, the call it wants made. It is our Python code that parses those arguments with `json.loads`, runs `search(**args)` against the index, and then serializes the result back into JSON with `json.dumps`. This JSON round-trip is the contract between the model and our runtime: the model emits structured intentions, we execute and report back structured outcomes. 

That separation is what makes function calling safe and useful. The LLM never touches our process directly, it only negotiates calls through a typed, serializable interface. To get an actual answer to the user we still need a second step: append the tool call and its result to `messages` and call the API again, so the model can read the search results and finally write the response. 


Now we send this result back to the model. First, we add the model's output to the conversation history. The model needs to see its own function call. Then we add the tool result.

This time the model has the original question, its own decision to call search, and the FAQ results. It can now produce a proper course-specific answer.

We have to send the whole history because LLMs are stateless between API calls. The memory is the list you send as input. If you send only the tool result, the model has no idea what's going on. So on this second call we replay everything we have so far. That means the question, the decision to call search, and the result we got back.

That's the full function-calling loop for a single turn. With plain RAG we made one call, and here we make two. Turning RAG agentic means more round-trips.

# Agentic Loop

An agent has three parts:

- Instructions, the role and behavior we want. We pass this as the developer message. The better the instructions, the better the agent helps.

- Tools, the functions the agent can call to carry out the task. For us that's only search.

- Memory, the message history. We append every prompt, every model output, and every tool result. The agent reads this to know what it has already tried.

Create function to receive a tool call from the LLM, running the tool locally, and formatting the result in the shape the API expects back.

This is the agentic loop wrapped as a reusable function that takes the agent's `instructions` and a `question` and returns the final answer as a string. It starts by building the initial conversation with the developer message (the instructions) and the user message (the question), then enters a `while True` loop. On each iteration it sends the full message history to the API along with the available tools, appends the model's entire output to `messages` so the next call sees what the model just said (this is how memory is built), and walks through every item in the output: when the item is a `function_call`, it runs `make_call` to execute the tool and appends the JSON result to `messages`, marking `has_function_calls = True` so the loop knows there is more to do; when the item is a `message`, it captures `item.content[0].text` into `last_answer` and prints it. After processing the output, if no function calls were made in this iteration, the model is signaling it has nothing more to look up and the loop breaks. The function returns the last assistant message it saw, which is the final answer to the user.

The agent searches for "Olama" and gets poor results. It then searches again with "Ollama" and finds the answer. The loop lets the model recover from a bad search on its own. That's the whole point of going agentic.

First, we will pull the lesson pages straight from the course repository. 
We will use the commit `8c1834d` to make sure everyone works with the exact same data.

We will use `gitsource` for that:
