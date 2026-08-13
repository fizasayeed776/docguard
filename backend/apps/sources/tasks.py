import hashlib
import logging
import os

from asgiref.sync import async_to_sync
from celery import shared_task
from channels.layers import get_channel_layer
from django.utils import timezone

logger = logging.getLogger(__name__)


def _publish_progress(workspace_id: str, event: str, message: str, **extra):
    """Send source-ingestion lifecycle updates to an open dashboard."""
    async_to_sync(get_channel_layer().group_send)(
        f"workspace_{workspace_id}_dashboard",
        {"type": "dashboard.event", "event": event, "message": message, **extra},
    )


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def sync_source(self, source_id: str):
    """List files for a Source (GitHub repo / upload set / wiki export),
    compute content hashes, and fan out one process_artifact task per file
    whose hash changed. Never processes unchanged files -> cheap re-syncs.
    """
    from .models import Source

    source = Source.objects.get(id=source_id)
    source.sync_status = Source.SyncStatus.SYNCING
    source.save(update_fields=["sync_status"])
    _publish_progress(
        str(source.workspace_id),
        "source_sync_started",
        f"Sync started: {source.name}",
        source_id=str(source.id),
    )

    try:
        files = _list_source_files(source)  # -> [{"path":..., "content": ...}, ...]
        dispatched = 0
        for f in files:
            content_hash = hashlib.sha256(f["content"].encode("utf-8")).hexdigest()
            process_artifact.delay(
                source_id=str(source.id),
                path=f["path"],
                content=f["content"],
                content_hash=content_hash,
                version=f.get("version", ""),
            )
            dispatched += 1

        source.sync_status = Source.SyncStatus.SYNCED
        source.last_synced_at = timezone.now()
        source.save(update_fields=["sync_status", "last_synced_at"])
        logger.info("sync_source: dispatched %s artifacts for source %s", dispatched, source_id)
        _publish_progress(
            str(source.workspace_id),
            "source_sync_completed",
            f"Sync complete: {source.name} — {dispatched} artifact(s) queued",
            source_id=str(source.id),
            artifact_count=dispatched,
        )
    except Exception as exc:
        source.sync_status = Source.SyncStatus.FAILED
        source.save(update_fields=["sync_status"])
        _publish_progress(
            str(source.workspace_id),
            "source_sync_failed",
            f"Sync failed: {source.name}",
            source_id=str(source.id),
        )
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=15)
def process_artifact(self, source_id: str, path: str, content: str, content_hash: str, version: str = ""):
    """Idempotent per-artifact processing. Skips work entirely if the
    content_hash is unchanged from the last time we saw this path - the
    core mechanism preventing duplicate work on webhook re-delivery."""
    from .models import Artifact

    artifact, created = Artifact.objects.get_or_create(
        source_id=source_id,
        path=path,
        defaults={
            "content_hash": content_hash,
            "raw_text": content,
            "version": version,
            "file_type": _infer_file_type(path),
        },
    )

    if not created and artifact.content_hash == content_hash:
        logger.info("process_artifact: %s unchanged, skipping", path)
        _publish_progress(
            str(artifact.source.workspace_id),
            "artifact_skipped",
            f"Unchanged: {path}",
            artifact_id=str(artifact.id),
        )
        return {"status": "skipped", "reason": "unchanged"}

    if not created:
        artifact.content_hash = content_hash
        artifact.raw_text = content
        artifact.version = version
        artifact.save(update_fields=["content_hash", "raw_text", "version", "updated_at"])

    chunks = _chunk_text(content, target_tokens=500, overlap_tokens=50)

    from apps.knowledge.tasks import embed_chunks

    embed_chunks.delay(artifact_id=str(artifact.id), chunks=chunks)
    _publish_progress(
        str(artifact.source.workspace_id),
        "artifact_processing",
        f"Processing: {path}",
        artifact_id=str(artifact.id),
        chunk_count=len(chunks),
    )

    return {"status": "processed", "artifact_id": str(artifact.id), "chunk_count": len(chunks)}


@shared_task
def check_source_freshness():
    """Hourly Beat task: flags sources that haven't synced recently."""
    from datetime import timedelta

    from .models import Source

    stale_cutoff = timezone.now() - timedelta(hours=24)
    stale = Source.objects.filter(last_synced_at__lt=stale_cutoff)
    for source in stale:
        logger.warning("Source %s is stale (last synced %s)", source.id, source.last_synced_at)
        sync_source.delay(str(source.id))


def _list_source_files(source):
    """Dispatch to GitHub API client, upload storage, or wiki export parser
    depending on source.type.

    For 'upload' sources, files are read directly from source.config, e.g.:
        {"files": [{"path": "README.md", "content": "..."}, ...]}
    This lets you test the full ingestion pipeline via the Django admin
    (paste JSON into the Source.config field) without needing GitHub set up.
    """
    from .models import Source

    if source.type == Source.Type.UPLOAD:
        files = source.config.get("files", [])
        if not files:
            logger.warning("Upload source %s has no files in config['files']", source.id)
        return files

    if source.type == Source.Type.GITHUB_REPO:
        return _get_github_files(source)

    raise NotImplementedError(
        f"'{source.type}' source type not implemented yet — only 'upload' is wired up so far."
    )


def get_github_files_for_paths(source, paths: list[str]) -> list[dict]:
    """Fetch only the files named by a GitHub push delivery."""
    return _get_github_files(source, paths=paths)


def _get_github_files(source, paths: list[str] | None = None) -> list[dict]:
    """Read repository files through GitHub's Contents API.

    Source.config needs ``repo`` as GitHub's ``owner/repository`` full name
    and may specify ``branch``. Authentication comes from the environment
    variable named by ``credentials_ref`` (or ``GITHUB_TOKEN``), never config.
    """
    from github import Github

    repo_name = source.config.get("repo", "")
    if not repo_name:
        raise ValueError(f"GitHub source {source.id} is missing config['repo']")
    token_env_name = source.credentials_ref or "GITHUB_TOKEN"
    token = os.environ.get(token_env_name, "")
    if not token:
        raise ValueError(f"GitHub source {source.id} has no token in {token_env_name!r}")

    repository = Github(token).get_repo(repo_name)
    branch = source.config.get("branch") or repository.default_branch
    requested_paths = paths if paths is not None else _github_repository_paths(repository, branch)
    files = []
    for path in requested_paths:
        try:
            contents = repository.get_contents(path, ref=branch)
        except Exception as exc:
            logger.info("GitHub source %s skipped %s: %s", source.id, path, exc)
            continue
        if isinstance(contents, list) or getattr(contents, "type", None) != "file":
            continue
        try:
            content = contents.decoded_content.decode("utf-8")
        except UnicodeDecodeError:
            logger.info("GitHub source %s skipped non-UTF-8 file %s", source.id, path)
            continue
        files.append({"path": path, "content": content, "version": contents.sha})
    return files


def _github_repository_paths(repository, branch: str) -> list[str]:
    tree = repository.get_git_tree(branch, recursive=True)
    return [item.path for item in tree.tree if item.type == "blob"]


def _infer_file_type(path: str) -> str:
    if path.endswith((".md", ".mdx")):
        return "markdown"
    if path.endswith(".pdf"):
        return "pdf"
    if "openapi" in path.lower() or path.endswith((".yaml", ".yml", ".json")):
        return "openapi"
    return "code_docstring"


def _chunk_text(text: str, target_tokens: int = 500, overlap_tokens: int = 50):
    """Naive whitespace-based chunker as a placeholder; swap for a real
    tokenizer (tiktoken) so target_tokens is accurate."""
    words = text.split()
    approx_words_per_chunk = target_tokens  # ~1 token/word placeholder ratio
    overlap = overlap_tokens
    chunks = []
    i = 0
    position = 0
    while i < len(words):
        chunk_words = words[i : i + approx_words_per_chunk]
        chunks.append({"text": " ".join(chunk_words), "position": position})
        position += 1
        i += approx_words_per_chunk - overlap
    return chunks
