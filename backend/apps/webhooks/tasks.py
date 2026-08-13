import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def handle_github_push(workspace_id: str, changed_paths: list[str], payload: dict):
    """Re-analyzes ONLY the artifacts affected by this push - the whole
    point of reacting to webhooks instead of relying only on scheduled
    full scans."""
    from apps.sources.models import Source
    from apps.sources.tasks import _list_source_files, process_artifact

    repo_full_name = payload.get("repository", {}).get("full_name", "")
    sources = Source.objects.filter(
        workspace_id=workspace_id, type=Source.Type.GITHUB_REPO, config__repo=repo_full_name
    )

    for source in sources:
        all_files = {f["path"]: f for f in _list_source_files(source)}
        for path in changed_paths:
            file_info = all_files.get(path)
            if not file_info:
                continue  # e.g. deleted file; deletion handling is a stretch item
            import hashlib

            content_hash = hashlib.sha256(file_info["content"].encode("utf-8")).hexdigest()
            process_artifact.delay(
                source_id=str(source.id),
                path=path,
                content=file_info["content"],
                content_hash=content_hash,
                version=file_info.get("version", ""),
            )
    logger.info("handle_github_push: dispatched %s changed paths for workspace %s", len(changed_paths), workspace_id)
