from __future__ import annotations

from typing import Any, Callable, Protocol


HttpJsonFn = Callable[..., tuple[int, dict[str, Any]]]


class LoggerLike(Protocol):
    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None: ...


def session_headers(msg: dict[str, str], agent_id: str) -> dict[str, str]:
    return {
        "organization-id": msg["organization_id"],
        "organization-address": msg["organization_address"],
        "conversation-id": msg["conversation_id"],
        "agent-id": agent_id,
        "contact-id": msg["contact_id"],
        "contact-address": msg["contact_address"],
    }


def session_get(
    session_base_url: str,
    conversation_id: str,
    *,
    http_json: HttpJsonFn,
    logger: LoggerLike,
) -> dict[str, Any] | None:
    status, data = http_json(
        method="GET",
        url=f"{session_base_url.rstrip('/')}/v1/sessions/{conversation_id}",
        timeout=45,
    )
    if status == 200 and isinstance(data, dict):
        return data
    if status == 404:
        return None
    logger.warning("session_get failed", extra={"status": status, "data": data})
    return None


def session_delete(
    session_base_url: str,
    conversation_id: str,
    *,
    http_json: HttpJsonFn,
    logger: LoggerLike,
) -> None:
    status, data = http_json(
        method="DELETE",
        url=f"{session_base_url.rstrip('/')}/v1/sessions/{conversation_id}",
        timeout=45,
    )
    if status not in (0, 200, 204):
        logger.warning("session_delete failed", extra={"status": status, "data": data})


def session_append_event(
    session_base_url: str,
    conversation_id: str,
    event_type: str,
    event_data: dict[str, Any],
    *,
    http_json: HttpJsonFn,
    logger: LoggerLike,
) -> None:
    status, data = http_json(
        method="POST",
        url=f"{session_base_url.rstrip('/')}/v1/sessions/{conversation_id}/events",
        body={"event_type": event_type, "event_data": event_data},
        timeout=45,
    )
    if status not in (0, 200):
        logger.warning(
            "session_append_event failed",
            extra={"status": status, "data": data, "event_type": event_type},
        )


def session_upsert(
    session_base_url: str,
    msg: dict[str, str],
    agent_id: str,
    variables: dict[str, Any],
    *,
    http_json: HttpJsonFn,
    logger: LoggerLike,
) -> None:
    status, data = http_json(
        method="POST",
        url=f"{session_base_url.rstrip('/')}/v1/sessions/upsert",
        body={
            "conversation_id": msg["conversation_id"],
            "organization_id": msg["organization_id"],
            "agent_id": agent_id,
            "contact_id": msg["contact_id"],
            "variables": variables,
        },
        timeout=45,
    )
    if status not in (0, 200):
        logger.warning("session_upsert failed", extra={"status": status, "data": data})


def try_session_get(
    session_base_url: str | None,
    conversation_id: str,
    *,
    http_json: HttpJsonFn,
    logger: LoggerLike,
) -> dict[str, Any] | None:
    if not session_base_url:
        return None
    try:
        return session_get(
            session_base_url,
            conversation_id,
            http_json=http_json,
            logger=logger,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("session_get exception: %s", exc)
        return None


def try_session_append_event(
    session_base_url: str | None,
    conversation_id: str,
    event_type: str,
    event_data: dict[str, Any],
    *,
    http_json: HttpJsonFn,
    logger: LoggerLike,
) -> None:
    if not session_base_url:
        return
    try:
        session_append_event(
            session_base_url,
            conversation_id,
            event_type,
            event_data,
            http_json=http_json,
            logger=logger,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("session_append_event exception: %s", exc)


def try_session_upsert(
    session_base_url: str | None,
    msg: dict[str, str],
    agent_id: str,
    variables: dict[str, Any],
    *,
    http_json: HttpJsonFn,
    logger: LoggerLike,
) -> None:
    if not session_base_url:
        return
    try:
        session_upsert(
            session_base_url,
            msg,
            agent_id,
            variables,
            http_json=http_json,
            logger=logger,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("session_upsert exception: %s", exc)


def try_session_delete(
    session_base_url: str | None,
    conversation_id: str,
    *,
    http_json: HttpJsonFn,
    logger: LoggerLike,
) -> None:
    if not session_base_url:
        return
    try:
        session_delete(
            session_base_url,
            conversation_id,
            http_json=http_json,
            logger=logger,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("session_delete exception: %s", exc)
