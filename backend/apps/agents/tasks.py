import logging
import re

from asgiref.sync import async_to_sync
from celery import shared_task
from channels.layers import get_channel_layer
from django.utils import timezone

logger = logging.getLogger(__name__)


def _get_structured_output(result):
    """Normalize various AgentResult shapes to a structured Python object.

    Strands' `AgentResult` may expose the model output under different
    attribute names depending on SDK/runtime. Try several plausible
    attributes and fall back to JSON parsing when the value is a string.
    Return an empty list or dict as a safe default depending on context
    (callers expect either a list of claim dicts or a dict verdict).
    """
    import json

    attrs = [
        "structured_output",
        "structured",
        "output",
        "outputs",
        "raw_output",
        "data",
        "response",
        "result",
        "content",
    ]

    for attr in attrs:
        if hasattr(result, attr):
            val = getattr(result, attr)
            try:
                # If it's a callable (some SDKs use callables), call it.
                if callable(val):
                    val = val()
            except Exception:
                logger.debug("_get_structured_output: calling %s() failed", attr, exc_info=True)

            # If it's a JSON string attempt to parse it.
            if isinstance(val, str):
                try:
                    parsed = json.loads(val)
                    return parsed
                except Exception:
                    # Not JSON — return the string (caller will handle)
                    return val

            return val

    # Try common dict-like conversions
    try:
        if hasattr(result, "to_dict"):
            d = result.to_dict()
            if isinstance(d, dict):
                return d.get("structured_output") or d.get("output") or d
    except Exception:
        logger.debug("_get_structured_output: to_dict() failed", exc_info=True)

    try:
        if hasattr(result, "json"):
            j = result.json()
            try:
                return json.loads(j) if isinstance(j, str) else j
            except Exception:
                return j
    except Exception:
        logger.debug("_get_structured_output: json() failed", exc_info=True)

    logger.warning("_get_structured_output: no structured output found on AgentResult; returning empty list/dict")
    return []

# ---------------------------------------------------------------------------
# Quota / rate-limit error detection
# ---------------------------------------------------------------------------

_QUOTA_PATTERNS = [
    r"429",
    r"quota",
    r"resource_exhausted",
    r"rate.?limit",
    r"too many requests",
]
_QUOTA_RE = re.compile("|".join(_QUOTA_PATTERNS), re.IGNORECASE)


def _is_quota_error(exc: Exception) -> bool:
    """Return True when *exc* looks like an AI-provider quota/rate-limit error."""
    return bool(_QUOTA_RE.search(str(exc)))


# ---------------------------------------------------------------------------
# WebSocket helpers
# ---------------------------------------------------------------------------

def _publish_progress(workspace_id: str, message: str, **extra):
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"workspace_{workspace_id}_dashboard",
        {"type": "dashboard.event", "event": "agent_activity", "message": message, **extra},
    )


def _publish_failure(workspace_id: str, message: str, **extra):
    """Publish a failed agent_activity event so the dashboard shows an error
    instead of staying empty."""
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"workspace_{workspace_id}_dashboard",
        {
            "type": "dashboard.event",
            "event": "agent_activity",
            "status": "failed",
            "message": message,
            **extra,
        },
    )


# ---------------------------------------------------------------------------
# Heuristic claim extractor (fallback when AI quota is exhausted)
# ---------------------------------------------------------------------------

_HEURISTIC_PATTERNS = [
    # Endpoint-like: GET /foo or POST /api/v1/bar
    (re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[\w/{}:.-]+)", re.IGNORECASE), "endpoint"),
    # API paths are frequently documented without an HTTP verb, e.g. /api/v2/users.
    (re.compile(r"(?<![\w.-])/(?:api(?:/v\d+(?:\.\d+)?)?|v\d+(?:\.\d+)?)(?:/[\w{}:.-]+)*", re.IGNORECASE), "endpoint"),
    # Rate limits written in prose, e.g. "rate limit is 60 requests per minute".
    (re.compile(r"\brate\s*limit\s*(?:is|:|=|of)?\s*\d+\s+requests?\s+(?:per|/)\s+(?:minute|min|second|sec|hour|day)\b", re.IGNORECASE), "rate_limit"),
    # Version strings: v1.2.3, version 2.0, etc.
    (re.compile(r"\b(version\s+[\d.]+|v\d+\.\d+[\d.]*)\b", re.IGNORECASE), "version_number"),
    # Config-value patterns: key = value or key: value
    (re.compile(r"\b([\w_]+)\s*[:=]\s*([\w./\"'-]+)\b"), "config_value"),
    # Process steps: lines starting with numbered list or "step N"
    (re.compile(r"(?:^|\n)\s*(?:\d+\.|step\s+\d+)[^\n]{10,80}", re.IGNORECASE), "process_step"),
]


def _heuristic_extract_claims(raw_text: str) -> list[dict]:
    """Regex-based claim extractor used as a fallback when the AI provider is
    quota-blocked.  Claims are clearly labelled with confidence=0.0 and a
    '[heuristic]' prefix so they are never confused with AI-validated output."""
    seen: set[str] = set()
    claims: list[dict] = []

    for pattern, category in _HEURISTIC_PATTERNS:
        for match in pattern.finditer(raw_text):
            statement = f"[heuristic] {match.group(0).strip()}"
            if statement not in seen:
                seen.add(statement)
                claims.append(
                    {
                        "statement": statement,
                        "category": category,
                        "confidence": 0.0,  # explicitly 0 — not AI-validated
                    }
                )

    return claims[:50]  # cap to avoid flooding the DB on large docs


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

@shared_task
def extract_claims(artifact_id: str):
    """Runs the Extractor agent over a freshly-embedded artifact.

    On AI-provider quota errors the task falls back to the heuristic
    extractor so the rest of the pipeline (compare_claim,
    judge_contradiction, dashboard events) can still be exercised.
    Any other exception publishes a 'failed' agent_activity event and
    persists the failure on the Artifact record.
    """
    from apps.knowledge.models import Claim
    from apps.sources.models import Artifact

    from .definitions import extractor_agent

    artifact = Artifact.objects.select_related("source__workspace").get(id=artifact_id)
    workspace_id = str(artifact.source.workspace_id)

    # Mark in-progress so a page refresh shows work is under way.
    artifact.extraction_status = Artifact.ExtractionStatus.IN_PROGRESS
    artifact.extraction_error = ""
    artifact.save(update_fields=["extraction_status", "extraction_error", "updated_at"])

    _publish_progress(workspace_id, f"Extractor: analyzing {artifact.path}")

    try:
        result = extractor_agent(f"artifact_id={artifact_id}")
        claims_data = _get_structured_output(result)  # list of {statement, category, confidence}
        extraction_status = Artifact.ExtractionStatus.COMPLETED
        extraction_label = "AI-validated"

    except Exception as exc:
        if _is_quota_error(exc):
            logger.warning(
                "extract_claims: AI quota exhausted for artifact %s — using heuristic fallback. error=%s",
                artifact_id,
                exc,
            )
            claims_data = _heuristic_extract_claims(artifact.raw_text)
            # Debug prints: some environments don't route logger output to stdout,
            logger.info("Heuristic extractor found %s candidate claims for artifact %s", len(claims_data), artifact_id)
            if claims_data:
                try:
                    logger.debug("Heuristic extractor sample claim: %r", claims_data[0])
                except Exception:
                    logger.debug("Unable to log heuristic extractor sample claim", exc_info=True)
            extraction_status = Artifact.ExtractionStatus.HEURISTIC
            extraction_label = "heuristic (AI quota exhausted)"
            artifact.extraction_status = extraction_status
            artifact.extraction_error = (
                "AI quota exhausted; heuristic extractor used. "
                "Claims are clearly labelled [heuristic] and have confidence=0."
            )
            artifact.save(update_fields=["extraction_status", "extraction_error", "updated_at"])

            _publish_failure(
                workspace_id,
                f"Extractor: AI quota exhausted for {artifact.path} — "
                f"falling back to heuristic extraction ({len(claims_data)} claims found). "
                "Claims are labelled [heuristic] and have confidence=0.",
                artifact_id=str(artifact_id),
                fallback="heuristic",
            )
        else:
            error_msg = f"Extractor failed for {artifact.path}: {exc}"
            logger.exception("extract_claims: unexpected error for artifact %s", artifact_id)

            # Persist failure state so a page refresh still shows it.
            artifact.extraction_status = Artifact.ExtractionStatus.FAILED
            artifact.extraction_error = str(exc)
            artifact.save(update_fields=["extraction_status", "extraction_error", "updated_at"])

            _publish_failure(
                workspace_id,
                error_msg,
                artifact_id=str(artifact_id),
            )
            raise  # re-raise so Celery marks the task as FAILURE

    claims = [
        Claim(
            artifact=artifact,
            statement=c["statement"],
            category=c["category"],
            confidence=c.get("confidence", 0.0),
        )
        for c in claims_data
    ]
    logger.debug("Creating %s Claim objects for artifact %s", len(claims), artifact_id)
    try:
        Claim.objects.bulk_create(claims)
        logger.debug("Claim bulk creation succeeded for artifact %s", artifact_id)
    except Exception:
        logger.exception("Claim bulk creation failed for artifact %s", artifact_id)
        # Attempt to save individually to capture per-item errors.
        for i, c in enumerate(claims):
            try:
                c.save()
            except Exception:
                logger.exception(
                    "Failed saving claim %s for artifact %s: %r",
                    i,
                    artifact_id,
                    getattr(c, "statement", None),
                )

    # Persist final status.
    artifact.extraction_status = extraction_status
    if extraction_status == Artifact.ExtractionStatus.COMPLETED:
        artifact.extraction_error = ""
    artifact.save(update_fields=["extraction_status", "extraction_error", "updated_at"])

    _publish_progress(
        workspace_id,
        f"Extractor: found {len(claims)} claims ({extraction_label}) in {artifact.path}",
        claim_count=len(claims),
        extraction_label=extraction_label,
    )

    for claim in claims:
        compare_claim.delay(claim_id=str(claim.id))


@shared_task
def compare_claim(claim_id: str):
    """Comparator agent checks a single Claim against the rest of the
    workspace's Claims via vector search; escalates contradictions to the
    Judge."""
    from apps.knowledge.models import Claim

    from .definitions import comparator_agent

    claim = Claim.objects.select_related("artifact__source__workspace").get(id=claim_id)
    workspace_id = str(claim.artifact.source.workspace_id)

    try:
        result = comparator_agent(
            f"claim_id={claim_id} statement={claim.statement!r} workspace_id={workspace_id}"
        )
        comp_out = _get_structured_output(result)
        contradictions = [c for c in comp_out if c.get("verdict") == "contradicts"]

    except Exception as exc:
        error_msg = (
            f"Comparator failed for claim {claim_id} "
            f"('{claim.statement[:60]}…'): {exc}"
        )
        logger.exception("compare_claim: unexpected error for claim %s", claim_id)
        _publish_failure(workspace_id, error_msg, claim_id=str(claim_id))
        raise

    for candidate in contradictions:
        judge_contradiction.delay(
            claim_id=str(claim.id),
            other_claim_id=candidate["other_claim_id"],
            comparator_reasoning=candidate["reasoning"],
        )


@shared_task
def judge_contradiction(claim_id: str, other_claim_id: str, comparator_reasoning: str):
    """Judge agent assigns severity and filters false positives."""
    from apps.knowledge.models import Claim, Inconsistency

    from .definitions import judge_agent

    claim = Claim.objects.select_related("artifact__source__workspace").get(id=claim_id)
    other_claim = Claim.objects.get(id=other_claim_id)
    workspace = claim.artifact.source.workspace
    workspace_id = str(workspace.id)

    try:
        result = judge_agent(
            f"Claim A: {claim.statement}\nClaim B: {other_claim.statement}\n"
            f"Comparator reasoning: {comparator_reasoning}"
        )
        verdict = _get_structured_output(result)  # {severity, is_false_positive, reasoning, suggested_fix}

    except Exception as exc:
        error_msg = (
            f"Judge failed for claims {claim_id} vs {other_claim_id}: {exc}"
        )
        logger.exception("judge_contradiction: unexpected error", exc_info=True)
        _publish_failure(
            workspace_id,
            error_msg,
            claim_id=str(claim_id),
            other_claim_id=str(other_claim_id),
        )
        raise

    if verdict.get("is_false_positive"):
        return

    inconsistency = Inconsistency.objects.create(
        workspace=workspace,
        severity=verdict["severity"],
        agent_reasoning=verdict["reasoning"],
        suggested_fix=verdict.get("suggested_fix", ""),
    )
    inconsistency.claims.set([claim, other_claim])

    from apps.workspaces.models import TriageRule

    _apply_triage_rules(inconsistency, TriageRule.objects.filter(workspace=workspace, is_active=True))

    _publish_progress(
        workspace_id,
        f"Judge: {verdict['severity']} inconsistency found",
        inconsistency_id=str(inconsistency.id),
        severity=verdict["severity"],
    )


def _apply_triage_rules(inconsistency, rules):
    import fnmatch

    for rule in rules:
        for claim in inconsistency.claims.all():
            if fnmatch.fnmatch(claim.artifact.path, rule.path_pattern):
                severity_order = ["minor", "major", "critical"]
                if severity_order.index(inconsistency.severity) <= severity_order.index(rule.max_severity):
                    inconsistency.status = rule.action
                    inconsistency.save(update_fields=["status"])
                return


@shared_task
def create_pull_request_from_fix(inconsistency_id: str):
    """Fixer agent drafts a corrected section and opens a GitHub PR."""
    from apps.knowledge.models import Inconsistency

    from .definitions import fixer_agent

    inconsistency = Inconsistency.objects.select_related("workspace").get(id=inconsistency_id)
    workspace_id = str(inconsistency.workspace_id)

    try:
        result = fixer_agent(
            f"inconsistency_id={inconsistency_id} suggested_fix={inconsistency.suggested_fix!r}"
        )
        pr_info = result.structured_output  # {pr_url, branch, commit_sha}

    except Exception as exc:
        error_msg = f"Fixer failed for inconsistency {inconsistency_id}: {exc}"
        logger.exception("create_pull_request_from_fix: unexpected error", exc_info=True)
        _publish_failure(workspace_id, error_msg, inconsistency_id=str(inconsistency_id))
        raise

    inconsistency.status = Inconsistency.Status.FIXED
    inconsistency.save(update_fields=["status", "updated_at"])

    _publish_progress(
        workspace_id,
        "Fixer: pull request created",
        inconsistency_id=str(inconsistency.id),
        pr_url=pr_info.get("pr_url"),
    )


@shared_task
def run_scan(workspace_id: str, trigger: str = "manual"):
    """Orchestrator entrypoint for a full or scoped scan."""
    from apps.knowledge.models import ScanRun
    from apps.sources.models import Artifact

    scan_run = ScanRun.objects.create(
        workspace_id=workspace_id,
        trigger=trigger,
        status=ScanRun.Status.RUNNING,
    )

    try:
        artifacts = Artifact.objects.filter(source__workspace_id=workspace_id)
        for artifact in artifacts:
            extract_claims.delay(artifact_id=str(artifact.id))

        scan_run.statistics = {"artifacts_scanned": artifacts.count()}
        scan_run.status = ScanRun.Status.COMPLETED
        scan_run.finished_at = timezone.now()
        scan_run.save(update_fields=["statistics", "status", "finished_at"])

    except Exception as exc:
        error_msg = f"run_scan failed for workspace {workspace_id}: {exc}"
        logger.exception("run_scan: unexpected error", exc_info=True)

        scan_run.status = ScanRun.Status.FAILED
        scan_run.error_message = str(exc)
        scan_run.finished_at = timezone.now()
        scan_run.save(update_fields=["status", "error_message", "finished_at"])

        _publish_failure(workspace_id, error_msg)
        raise

    return str(scan_run.id)


@shared_task
def run_full_scan_all_workspaces():
    """Nightly Celery Beat task."""
    from apps.workspaces.models import Workspace

    for workspace in Workspace.objects.all():
        run_scan.delay(workspace_id=str(workspace.id), trigger="scheduled")
