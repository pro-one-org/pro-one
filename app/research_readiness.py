"""Local operational checks for a controlled research instance."""

from contextlib import closing
from pathlib import Path
import sqlite3


def research_readiness(settings, registry):
    model_configured = (settings.provider in {"openai", "anthropic"}
                        and settings.model in registry.configured_models().get(settings.provider, []))
    checks = {
        "research_mode_available": settings.mode == "development",
        "live_model_configured": model_configured,
        "shared_conversation_key_configured": settings.conversation_signing_key is not None,
        "virginia_corpus_available": _virginia_corpus_available(settings),
    }
    return {"status": "ready" if all(checks.values()) else "not_ready", "checks": checks,
            "release_approved": False}


def _virginia_corpus_available(settings):
    path = settings.corpus_path or (".local/courtlistener.sqlite3" if settings.courtlistener_enabled else "")
    if not path or path == ":memory:":
        return False
    try:
        uri = Path(path).absolute().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=0.25)) as connection:
            # A probe must yield promptly even for a large, incomplete corpus.
            connection.set_progress_handler(lambda: 1, 100000)
            row = connection.execute("""
                SELECT 1 FROM courts AS court
                JOIN dockets AS docket ON docket.court=court.id
                JOIN clusters AS cluster ON cluster.docket=docket.id
                JOIN opinions AS opinion ON opinion.cluster=cluster.id
                WHERE court.state='Virginia' AND court.sovereign='state'
                    AND cluster.origin IN ('courtlistener_v4', 'courtlistener_bulk')
                    AND opinion.state='available' AND opinion.text!=''
                LIMIT 1
            """).fetchone()
            return row is not None
    except (OSError, ValueError, sqlite3.Error):
        return False
