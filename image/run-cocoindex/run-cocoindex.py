#!/usr/bin/env python3
"""
run-cocoindex - CLI entrypoint for Jenkins pipeline
"""

import argparse
import asyncpg
import cocoindex as coco
import hashlib
import logging
import os
import re
import subprocess
import sys
import traceback
import yaml

from pathlib import Path
from numpy.typing import NDArray
from cocoindex.connectors import localfs, postgres
from cocoindex.ops.litellm import LiteLLMEmbedder
from cocoindex.ops.text import RecursiveSplitter, detect_code_language
from cocoindex.resources.file import FileLike, PatternFilePathMatcher
from dataclasses import dataclass
from typing import Annotated, AsyncIterator

__scriptName__ = os.path.basename(sys.argv[0])

# ====================== LOGGING SETUP ======================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_LEVEL_NUMERIC = getattr(logging, LOG_LEVEL, logging.INFO)
logger = logging.getLogger(__scriptName__)

logging.basicConfig(
    format="%(name)s - %(levelname)-8s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger.setLevel(LOG_LEVEL_NUMERIC)

# Configuration & Remote Embedding API Settings
COCOINDEX_DB_URL = os.getenv(
    "COCOINDEX_DB_URL",
    "postgres://cocoindex:cocoindex@postgres-cocoindex:5432/cocoindex",
)
COCO_EMBED_MODEL = os.getenv("COCO_EMBED_MODEL", "nomic-embed-text")
EMBEDDING_API_BASE = os.getenv("EMBEDDING_API_BASE", "http://vllm:8000/v1")
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "EMPTY")

COCO_PG_DB = coco.ContextKey[asyncpg.Pool]("worker_repo_index_db")
COCO_EMBEDDER = coco.ContextKey[LiteLLMEmbedder]("worker_repo_index_embedder", detect_change=True)

DEFAULT_COCO_CONFIG: dict = {
    "app": {"name": "default-collection", "max_inflight_components": 8},
    "environment": {"db_path": ".cocoindex/cocoindex.db"},
    "sources": [
        {
            "type": "local_files",
            "path": ".",
            "include": ["**/*.py", "**/*.md", "**/*.yml", "**/*.yaml", "**/*.json", "**/*.groovy", "**/*.sh"],
            "exclude": [".git/**", "__pycache__/**", "venv/**", ".venv/**", "node_modules/**"],
        }
    ],
    "storage": {
        "type": "postgres",
        "table_name": None
    }
}


@dataclass
class RepoCodeEmbedding:
    id: str
    filename: str
    code: str
    embedding: Annotated[NDArray, COCO_EMBEDDER]
    start_line: int
    end_line: int


@coco.lifespan
async def coco_repo_index_lifespan(builder: "coco.EnvironmentBuilder") -> AsyncIterator[None]:
    async with asyncpg.create_pool(COCOINDEX_DB_URL) as pool:
        builder.provide(COCO_PG_DB, pool)
        # Use remote LiteLLM-compatible API endpoint for generating embeddings
        embedder = LiteLLMEmbedder(
            model=COCO_EMBED_MODEL,
            api_base=EMBEDDING_API_BASE,
            api_key=EMBEDDING_API_KEY,
        )
        builder.provide(COCO_EMBEDDER, embedder)
        yield


def generate_stable_chunk_id(filename: str, start_line: int, text: str) -> str:
    """Generate a globally unique, stable ID for each chunk"""
    # Combine file path + line number + hash of content
    content_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]
    key = f"{filename}:{start_line}:{content_hash}"
    return hashlib.sha256(key.encode('utf-8')).hexdigest()[:32]


@coco.fn(memo=True)
async def _repo_index_process_chunk(chunk, filename: Path, table) -> None:
    embedder = coco.use_context(COCO_EMBEDDER)
    embedding = await embedder.embed(chunk.text)

    chunk_id = generate_stable_chunk_id(
        filename=str(filename),
        start_line=chunk.start.line,
        text=chunk.text
    )

    table.declare_row(
        row=RepoCodeEmbedding(
            id=chunk_id,
            filename=str(filename),
            code=chunk.text,
            embedding=embedding,
            start_line=chunk.start.line,
            end_line=chunk.end.line,
        ),
    )


@coco.fn(memo=True)
async def _repo_index_process_file(file: FileLike, table: "postgres.TableTarget[RepoCodeEmbedding]") -> None:
    text = await file.read_text()
    language = detect_code_language(filename=str(file.file_path.path.name))
    chunks = RecursiveSplitter().split(
        text,
        chunk_size=1000,
        min_chunk_size=300,
        chunk_overlap=300,
        language=language,
    )
    await coco.map(_repo_index_process_chunk, chunks, file.file_path.path, table)


@coco.fn
async def _repo_index_main(
    source_dir: Path,
    table_name: str,
    included_patterns: list,
    excluded_patterns: list,
) -> None:
    pool = coco.use_context(COCO_PG_DB)

    # Pre-check: Does the table exist in the postgres catalog?
    table_exists = False
    async with pool.acquire() as conn:
        table_exists = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = $1
            );
            """,
            table_name,
        )

    if table_exists:
        logger.info(
            f"Table '{table_name}' already exists. Preparing structure for sync."
        )
        # Since CocoIndex's DAG state builder throws an error if we re-call mount_table_target,
        # and it throws an error if we call it when the relation exists, we clear the relation name
        # inside Postgres metadata context or handle data migration safely.

        # To bypass CocoIndex's strict DDL engine while keeping your data for the sync,
        # we can temporarily rename the table, let CocoIndex think it's fresh, and merge.
        async with pool.acquire() as conn:
            await conn.execute(
                f'ALTER TABLE "{table_name}" RENAME TO "{table_name}_old";'
            )

    # Now call mount_table_target EXACTLY ONCE so the DAG remains valid
    target_table = await postgres.mount_table_target(
        COCO_PG_DB,
        table_name=table_name,
        table_schema=await postgres.TableSchema.from_class(
            RepoCodeEmbedding,
            primary_key=["id"],
        ),
    )
    target_table.declare_vector_index(column="embedding")

    if table_exists:
        logger.info(f"Merging existing records for '{table_name}'...")
        async with pool.acquire() as conn:
            # Upsert old data into the new table structure to keep existing embeddings
            await conn.execute(f"""
                INSERT INTO "{table_name}" SELECT * FROM "{table_name}_old"
                ON CONFLICT (id) DO NOTHING;
            """)
            await conn.execute(f'DROP TABLE IF EXISTS "{table_name}_old" CASCADE;')

    # Proceed with the incremental filesystem scan
    files = localfs.walk_dir(
        source_dir,
        recursive=True,
        path_matcher=PatternFilePathMatcher(
            included_patterns=included_patterns,
            excluded_patterns=excluded_patterns,
        ),
        live=False,
    )
    await coco.mount_each(_repo_index_process_file, files.items(), target_table)


def get_repo_slug(workspace_path: Path) -> str:
    """Best-effort repo identifier for table name"""
    try:
        # Try git remote first (most reliable)
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            # Extract owner/repo from https://.../owner/repo.git or git@...:owner/repo.git
            match = re.search(r'[:/]([^/]+/[^/]+?)(?:\.git)?$', url)
            if match:
                slug = match.group(1).replace('/', '_').lower()
                return re.sub(r'[^a-z0-9_]', '_', slug)
    except Exception:
        pass

    # Fallback: sanitized workspace directory name
    return re.sub(r'[^a-z0-9_]', '_', workspace_path.name.lower())


def build_repo_index(workspace_path: Path):
    """Parses .cocoindex.yml and runs indexing with remote embedding endpoint"""
    try:
        config_path = workspace_path / ".cocoindex.yml"
        config_data = DEFAULT_COCO_CONFIG.copy()

        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                user_config = yaml.safe_load(f) or {}
                config_data.update(user_config)
                if "storage" in user_config:
                    config_data.setdefault("storage", {}).update(user_config["storage"])
        else:
            logger.warning(f"No .cocoindex.yml found at {config_path}. Using defaults.")

        if not COCOINDEX_DB_URL:
            logger.warning("[Repo Index] No COCOINDEX_DB_URL - skipping index.")
            return

        # === Determine table_name (priority: config > auto-generated) ===
        storage_config = config_data.get("storage", {})
        table_name = storage_config.get("table_name")

        if not table_name:
            repo_slug = get_repo_slug(workspace_path)
            table_name = f"repo_idx_{repo_slug}"
            logger.info(f"Using auto-generated table name: {table_name}")

        # Parse App configurations
        app_settings = config_data.get("app", {})
        app_name = app_settings.get("name", "codebase-agent-index")

        # Resolve state DB path and inject into environment
        env_settings = config_data.get("environment", {})
        db_path_raw = env_settings.get("db_path", ".cocoindex/cocoindex.db")
        db_path_abs = os.path.abspath(os.path.join(workspace_path, db_path_raw))

        # Ensure the parent directory for the state file exists locally
        os.makedirs(os.path.dirname(db_path_abs), exist_ok=True)
        os.environ["COCOINDEX_DB"] = db_path_abs

        # Source patterns
        source_settings = (config_data.get("sources") or [{}])[0]
        included_patterns = source_settings.get(
            "include", ["**/*.py", "**/*.md", "**/*.yml", "**/*.yaml", "**/*.json"]
        )
        excluded_patterns = source_settings.get(
            "exclude", [".git/**", "__pycache__/**", "venv/**", ".venv/**"]
        )

        logger.info(f"Indexing into table: {table_name}")

        app = coco.App(
            coco.AppConfig(name=app_name),
            _repo_index_main,
            source_dir=Path(workspace_path),
            table_name=table_name,
            included_patterns=included_patterns,
            excluded_patterns=excluded_patterns,
        )

        logger.info("Starting CocoIndex incremental update...")
        app.update_blocking()
        logger.info("✅ CocoIndex update completed successfully")

    except Exception as e:
        logger.error(f"❌ CocoIndex pipeline failed: {e}")
        traceback.print_exc()
        raise


def main():
    parser = argparse.ArgumentParser(description="CocoIndex Runner")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()

    if args.verbose >= 2:
        logging.getLogger().setLevel(logging.DEBUG)

    workspace = Path(os.getenv("WORKSPACE", ".")).resolve()
    logger.info(f"Starting CocoIndex in workspace: {workspace}")

    try:
        build_repo_index(workspace)
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ CocoIndex pipeline failed: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
