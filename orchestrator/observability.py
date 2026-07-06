from __future__ import annotations

from typing import Any, Callable


EnvFn = Callable[[str, str | None], str | None]
IsCloudRuntimeFn = Callable[[], bool]


def parse_bool_query(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _normalize_deployment_url(raw_url: str | None) -> str:
    if not raw_url:
        return "unknown"
    cleaned = raw_url.strip()
    if not cleaned:
        return "unknown"
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        return cleaned
    return f"https://{cleaned}"


def _resolve_app_version(env: EnvFn, commit_sha: str, deployment_id: str) -> str:
    explicit = (env("APP_VERSION", None) or "").strip()
    if explicit:
        return explicit

    if commit_sha and commit_sha != "unknown":
        return f"git-{commit_sha[:12]}"

    if deployment_id and deployment_id != "unknown":
        return f"deploy-{deployment_id}"

    return "dev"


def build_version_payload(
    *,
    env: EnvFn,
    is_cloud_runtime: IsCloudRuntimeFn,
    python_version: str,
) -> dict[str, Any]:
    commit_sha = (
        env("VERCEL_GIT_COMMIT_SHA", None)
        or env("COMMIT_SHA", None)
        or env("GIT_COMMIT", None)
        or "unknown"
    )
    deployment_id = env("VERCEL_DEPLOYMENT_ID", None) or env("RENDER_SERVICE_ID", None) or "unknown"
    deployment_url = _normalize_deployment_url(env("VERCEL_URL", None))
    deployment = deployment_id if deployment_id != "unknown" else deployment_url
    version = _resolve_app_version(env, commit_sha, deployment_id)
    return {
        "service": "acomara-orchestrator",
        "environment": env("VERCEL_ENV", env("ENV", "unknown")),
        "runtime_mode": "cloud" if is_cloud_runtime() else "local",
        "version": version,
        "commit": commit_sha,
        "commit_short": commit_sha[:12] if commit_sha != "unknown" else "unknown",
        "deployed_at": env("BUILD_TIMESTAMP", "unknown"),
        "deployment_id": deployment_id,
        "deployment_url": deployment_url,
        "deployment": deployment,
        "python": python_version,
        "features": {
            "email_verification_enabled": str(env("EMAIL_VERIFICATION_ENABLED", "true") or "true")
            .strip()
            .lower()
            in ("1", "true", "yes", "on"),
            "has_hibp_api_key": bool(env("HIBP_API_KEY", None)),
            "has_session_agent": bool(env("SESSION_AGENT_BASE_URL", None)),
            "handoff_provider": env("HANDOFF_EMAIL_PROVIDER", "resend"),
            "openai_embed_model": env("OPENAI_EMBED_MODEL", "text-embedding-3-large"),
            "openai_chat_model": env("OPENAI_CHAT_MODEL", "gpt-5.4"),
            "chat_model_from_request": str(env("OPENAI_CHAT_MODEL_FROM_REQUEST", "false") or "false")
            .strip()
            .lower()
            in ("1", "true", "yes", "on"),
            "openai_allowed_chat_models": [
                part.strip()
                for part in str(env("OPENAI_ALLOWED_CHAT_MODELS", "") or "").split(",")
                if part.strip()
            ],
        },
    }


def build_version_text(payload: dict[str, Any]) -> str:
    features = payload["features"]
    return "\n".join(
        [
            f"Servicio: {payload['service']}",
            f"Environment: {payload['environment']}",
            f"Version: {payload['version']}",
            f"Commit: {payload['commit_short']}",
            f"Deployment ID: {payload['deployment_id']}",
            f"Deployment URL: {payload['deployment_url']}",
            f"Python: {payload['python']}",
            f"Email verification: {'on' if features['email_verification_enabled'] else 'off'}",
            f"HIBP key: {'configured' if features['has_hibp_api_key'] else 'missing'}",
            f"Session agent: {'configured' if features['has_session_agent'] else 'missing'}",
            f"Handoff provider: {features['handoff_provider']}",
            f"OpenAI embed model: {features['openai_embed_model']}",
            f"OpenAI chat model: {features['openai_chat_model']}",
            f"Chat model override from request: {'on' if features['chat_model_from_request'] else 'off'}",
            "OpenAI allowed chat models: "
            + (
                ", ".join(features["openai_allowed_chat_models"])
                if features["openai_allowed_chat_models"]
                else "(any)"
            ),
        ]
    )


def build_health_response(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "ok",
        "service": payload["service"],
        "version": payload["version"],
        "commit": payload["commit_short"],
    }


def build_safe_version_response(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "service": payload["service"],
        "environment": payload["environment"],
        "runtime_mode": payload["runtime_mode"],
        "version": payload["version"],
        "commit": payload["commit_short"],
        "deployment_id": payload["deployment_id"],
        "deployment_url": payload["deployment_url"],
        "features": {
            "email_verification_enabled": payload["features"]["email_verification_enabled"],
            "has_hibp_api_key": payload["features"]["has_hibp_api_key"],
            "has_session_agent": payload["features"]["has_session_agent"],
            "handoff_provider": payload["features"]["handoff_provider"],
            "openai_embed_model": payload["features"]["openai_embed_model"],
            "openai_chat_model": payload["features"]["openai_chat_model"],
            "chat_model_from_request": payload["features"]["chat_model_from_request"],
            "openai_allowed_chat_models": payload["features"]["openai_allowed_chat_models"],
        },
    }


def render_audit_dashboard_html(report: dict[str, Any]) -> str:
    totals = report.get("totals", {})
    issue_counts = report.get("issue_counts", {})
    status_counts = report.get("status_counts", {})
    message_stats = report.get("message_stats", {})
    problematic = report.get("problematic_conversations", [])

    issue_rows = "".join(
        f"<tr><td>{issue}</td><td>{count}</td></tr>"
        for issue, count in sorted(issue_counts.items(), key=lambda item: item[1], reverse=True)
    )
    if not issue_rows:
        issue_rows = "<tr><td colspan='2'>No issues detected</td></tr>"

    problem_rows = "".join(
        "<tr>"
        f"<td>{row.get('conversation_id', '-')}</td>"
        f"<td>{row.get('message_count', 0)}</td>"
        f"<td>{', '.join(row.get('issues', []))}</td>"
        "</tr>"
        for row in problematic[:20]
    )
    if not problem_rows:
        problem_rows = "<tr><td colspan='3'>No problematic conversations in current window</td></tr>"

    return f"""
<!doctype html>
<html lang='es'>
<head>
    <meta charset='utf-8' />
    <meta name='viewport' content='width=device-width, initial-scale=1' />
    <title>Acomara Audit Dashboard</title>
    <style>
        :root {{
            --bg: #f6f7f9;
            --panel: #ffffff;
            --ink: #1a2433;
            --muted: #6a7485;
            --accent: #0b6db7;
            --warn: #d9480f;
            --ok: #1b7f3b;
        }}
        * {{ box-sizing: border-box; }}
        body {{ margin: 0; font-family: "IBM Plex Sans", "Segoe UI", sans-serif; background: radial-gradient(circle at top right, #e6f2fb 0%, var(--bg) 45%); color: var(--ink); }}
        .wrap {{ max-width: 1160px; margin: 0 auto; padding: 28px 20px 40px; }}
        h1 {{ margin: 0; font-size: 1.7rem; letter-spacing: 0.2px; }}
        .meta {{ margin-top: 6px; color: var(--muted); font-size: 0.95rem; }}
        .grid {{ margin-top: 18px; display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; }}
        .card {{ background: var(--panel); border: 1px solid #dde3ea; border-radius: 12px; padding: 14px; box-shadow: 0 4px 14px rgba(14, 33, 53, 0.05); }}
        .label {{ color: var(--muted); font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.04em; }}
        .value {{ margin-top: 6px; font-size: 1.45rem; font-weight: 700; }}
        .value.ok {{ color: var(--ok); }}
        .value.warn {{ color: var(--warn); }}
        h2 {{ margin: 22px 0 10px; font-size: 1.05rem; }}
        table {{ width: 100%; border-collapse: collapse; background: var(--panel); border-radius: 12px; overflow: hidden; border: 1px solid #dde3ea; }}
        th, td {{ padding: 10px 12px; border-bottom: 1px solid #edf1f5; text-align: left; font-size: 0.92rem; vertical-align: top; }}
        th {{ background: #f2f7fc; color: #314257; font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.04em; }}
        tr:last-child td {{ border-bottom: 0; }}
        .foot {{ margin-top: 14px; color: var(--muted); font-size: 0.85rem; }}
    </style>
</head>
<body>
    <div class='wrap'>
        <h1>Acomara Conversation Audit</h1>
        <div class='meta'>Generado: {report.get('generated_at', '-')} | Organization: {report.get('organization_id', '-')}</div>

        <div class='grid'>
            <div class='card'><div class='label'>Conversaciones auditadas</div><div class='value'>{totals.get('audited_conversations', 0)}</div></div>
            <div class='card'><div class='label'>Con problemas</div><div class='value warn'>{totals.get('conversations_with_issues', 0)}</div></div>
            <div class='card'><div class='label'>Quality rate</div><div class='value ok'>{totals.get('quality_rate_percent', 0)}%</div></div>
            <div class='card'><div class='label'>Mensajes totales</div><div class='value'>{message_stats.get('total_messages', 0)}</div></div>
            <div class='card'><div class='label'>Promedio mensajes</div><div class='value'>{message_stats.get('avg', 0)}</div></div>
            <div class='card'><div class='label'>Estado OK</div><div class='value'>{status_counts.get('OK', 0)}</div></div>
        </div>

        <h2>Problemas por tipo</h2>
        <table>
            <thead><tr><th>Tipo</th><th>Cantidad</th></tr></thead>
            <tbody>{issue_rows}</tbody>
        </table>

        <h2>Conversaciones problematicas (top 20 por tamano)</h2>
        <table>
            <thead><tr><th>Conversation ID</th><th>Mensajes</th><th>Issues</th></tr></thead>
            <tbody>{problem_rows}</tbody>
        </table>

        <div class='foot'>
            Query options: days_back, include_test, organization_id, api_key
        </div>
    </div>
</body>
</html>
"""
