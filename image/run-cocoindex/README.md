# run-cocoindex Container Image

`run-cocoindex` is a containerized utility designed to parse code repositories, generate vector embeddings via an external OpenAI-compatible LLM/embedding endpoint, and perform incremental indexing into a PostgreSQL vector database using [CocoIndex](https://github.com/cocoindex-io/cocoindex). It is optimized to run as a standalone CLI or inside CI/CD pipelines (such as Jenkins).

---

## 🌟 Features

* **External LLM/Embedding Endpoint Support:** Uses `OpenAIEmbedder` to generate code embeddings from any OpenAI-compatible API endpoint (e.g., vLLM, Ollama, LiteLLM).
* **Incremental Code Indexing:** Parses codebase files, splits them into semantic chunks using language-aware recursive splitters, and updates vector indexes incrementally.
* **Automatic Table Naming & Safe Migration:** Automatically derives PostgreSQL target table names from Git remote URLs or workspace names, with built-in schema migration handling.
* **Configurable Patterns:** Supports file inclusion/exclusion rules via environment variables or a local `.cocoindex.yml` file.
* **Pipeline-Ready:** Package includes a CLI runner built for execution inside Docker-based CI/CD workflows.

---

## 🚀 Quick Start & CLI Usage

### Basic CLI Usage

Run `run-cocoindex` directly inside your target repository workspace:

```bash
run-cocoindex [OPTIONS]
```

#### CLI Options
* `-v, --verbose`: Increase verbosity level. Use `-vv` to enable `DEBUG` logging.

#### Example
```bash
# Run with standard logging
run-cocoindex

# Run with verbose debug logging
run-cocoindex -vv
```

---

## 🐋 Running with Docker

### Basic Docker Execution

Mount your target repository workspace directory into the container, set the external embedding API variables, and execute `run-cocoindex`:

```bash
docker run --rm \
  -v $(pwd):/workspace \
  -w /workspace \
  -e COCOINDEX_DB_URL="postgres://cocoindex:cocoindex@postgres-cocoindex:5432/cocoindex" \
  -e EMBEDDING_API_BASE="http://vllm:8000/v1" \
  -e EMBEDDING_API_KEY="${EMBEDDING_API_KEY}" \
  -e COCO_EMBED_MODEL="openai/nomic-embed-text" \
  media.johnson.int:5000/run-cocoindex:latest \
  run-cocoindex
```

> **Note:** Execute `run-cocoindex` directly. Do **not** prefix the command with `python` (e.g., `python run-cocoindex`).

---

## ⚙️ Configuration

### Environment Variables

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `COCOINDEX_DB_URL` | `postgres://cocoindex:cocoindex@postgres-cocoindex:5432/cocoindex` | Target PostgreSQL vector database connection string. |
| `EMBEDDING_API_BASE` | `http://vllm:8000/v1` | Base URL for the OpenAI-compatible embedding service endpoint. |
| `EMBEDDING_API_KEY` | `EMPTY` | API key for authenticating with the external embedding endpoint. |
| `COCO_EMBED_MODEL` | `nomic-embed-text` | Name of the embedding model served by the external endpoint. |
| `LOG_LEVEL` | `INFO` | Sets application logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `WORKSPACE` | `.` | Root directory path of the codebase to index. |

---

### File Configuration (`.cocoindex.yml`)

You can customize repository indexing parameters by adding a `.cocoindex.yml` file to the root directory of your project:

```yaml
app:
  name: codebase-agent-index
  max_inflight_components: 8

environment:
  db_path: .cocoindex/cocoindex.db

sources:
  - type: local_files
    path: .
    include:
      - "**/*.py"
      - "**/*.md"
      - "**/*.yml"
      - "**/*.yaml"
      - "**/*.json"
      - "**/*.groovy"
      - "**/*.sh"
    exclude:
      - ".git/**"
      - "__pycache__/**"
      - "venv/**"
      - ".venv/**"
      - "node_modules/**"

storage:
  type: postgres
  table_name: custom_repo_index_table  # Optional: defaults to repo_idx_<repo_slug>
```

---

## 🛠 Jenkins Pipeline Integration

When invoking `run-cocoindex` in a Jenkins pipeline, pass the required environment variables to configure connection details for your external embedding provider and PostgreSQL database:

```groovy
pipeline {
    agent {
        docker {
            image 'media.johnson.int:5000/run-cocoindex:latest'
            args '-u root:root --network host'
        }
    }
    environment {
        COCOINDEX_DB_URL   = 'postgres://cocoindex:cocoindex@postgres-cocoindex:5432/cocoindex'
        EMBEDDING_API_BASE = '[http://gpu02.johnson.int:11434/v1](http://gpu02.johnson.int:11434/v1)'
        COCO_EMBED_MODEL   = 'nomic-embed-text'
    }
    stages {
        stage('CocoIndex: Update Index') {
            steps {
                sh 'run-cocoindex -v'
            }
        }
    }
}
```
