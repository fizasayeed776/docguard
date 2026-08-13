import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def handle_github_push(workspace_id: str, changed_paths: list[str], payload: dict):
    """Re-analyzes ONLY the artifacts affected by this push - the whole
    point of reacting to webhooks instead of relying only on scheduled
    full scans."""
    from apps.sources.models import Source
    from apps.sources.tasks import get_github_files_for_paths, process_artifact

    repo_full_name = payload.get("repository", {}).get("full_name", "")
    sources = list(Source.objects.filter(
        workspace_id=workspace_id, type=Source.Type.GITHUB_REPO, config__repo=repo_full_name
    ))
    if not sources:
        logger.warning(
            "handle_github_push: no GitHub Source for workspace=%s repo=%r; no work dispatched",
            workspace_id,
            repo_full_name,
        )
        return {"sources": 0, "dispatched": 0}

    dispatched = 0
    for source in sources:
        for file_info in get_github_files_for_paths(source, changed_paths):
            import hashlib

            content_hash = hashlib.sha256(file_info["content"].encode("utf-8")).hexdigest()
            process_artifact.delay(
                source_id=str(source.id),
                path=file_info["path"],
                content=file_info["content"],
                content_hash=content_hash,
                version=file_info.get("version", ""),
            )
            dispatched += 1
    logger.info(
        "handle_github_push: dispatched %s changed file(s) to %s source(s) for workspace %s",
        dispatched,
        len(sources),
        workspace_id,
    )
    return {"sources": len(sources), "dispatched": dispatched}
