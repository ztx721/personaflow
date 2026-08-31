"""Deterministic application policy for lightweight unfinished topics."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from ..schemas import (
    ConversationSignals,
    ConversationState,
    OpenThread,
    OpenThreadStatus,
    ThreadUpdate,
    ThreadUpdateAction,
)

MAX_ACTIVE_THREADS = 5
MAX_TOPIC_LENGTH = 48
MAX_SUMMARY_LENGTH = 120

_BOUNDARY_MARKERS = ("不想聊", "别再提", "忘了吧", "算了吧", "不聊这个")
_POSTPONE_MARKERS = ("以后再说", "回头再说", "先不说这个", "晚点再说")
_INTERNAL_MARKERS = (
    "system prompt", "planner", "story node", "story engine", "social_action",
    "conversation_guidance", "relationship_context", "emotion_context",
    "asset_tag", "node_id", "<system", "<planner", "```", "系统提示",
    "内部指令", "隐藏推理",
)
_SAFE_TEXT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class ThreadApplicationResult:
    def __init__(self) -> None:
        self.opened: list[str] = []
        self.touched: list[str] = []
        self.resolved: list[str] = []
        self.resumed: OpenThread | None = None


def active_threads(state: ConversationState) -> list[OpenThread]:
    active = [item for item in state.open_threads if item.status is OpenThreadStatus.open]
    return sorted(active, key=lambda item: (-item.priority, -item.last_touched_turn, item.id))[
        :MAX_ACTIVE_THREADS
    ]


def apply_thread_updates(
    state: ConversationState,
    updates: list[ThreadUpdate],
    resume_thread_id: str | None,
    turn_number: int,
    user_message: str,
    signals: ConversationSignals,
) -> ThreadApplicationResult:
    result = ThreadApplicationResult()
    by_id = {item.id: item for item in state.open_threads}

    if any(marker in user_message for marker in _BOUNDARY_MARKERS):
        target = _most_recent_active(state)
        if target is not None:
            target.status = OpenThreadStatus.resolved
            target.last_touched_turn = turn_number
            result.resolved.append(target.id)

    for update in updates[:5]:
        if update.action is ThreadUpdateAction.open:
            topic = _safe_text(update.topic, MAX_TOPIC_LENGTH)
            summary = _safe_text(update.summary, MAX_SUMMARY_LENGTH)
            if not topic or not summary or _duplicate(state, topic):
                continue
            _make_room(state, result)
            thread = OpenThread(
                id=_next_id(state, turn_number),
                topic=topic,
                summary=summary,
                owner=update.owner,
                created_turn=turn_number,
                last_touched_turn=turn_number,
                priority=update.priority,
            )
            state.open_threads.append(thread)
            by_id[thread.id] = thread
            result.opened.append(thread.id)
        elif update.thread_id and update.thread_id in by_id:
            thread = by_id[update.thread_id]
            if thread.status is not OpenThreadStatus.open:
                continue
            if update.action is ThreadUpdateAction.resolve:
                thread.status = OpenThreadStatus.resolved
                thread.last_touched_turn = turn_number
                result.resolved.append(thread.id)
            elif update.action is ThreadUpdateAction.touch:
                topic = _safe_text(update.topic, MAX_TOPIC_LENGTH)
                summary = _safe_text(update.summary, MAX_SUMMARY_LENGTH)
                if topic:
                    thread.topic = topic
                if summary:
                    thread.summary = summary
                thread.last_touched_turn = turn_number
                thread.priority = update.priority
                result.touched.append(thread.id)

    postponed = any(marker in user_message for marker in _POSTPONE_MARKERS)
    boundary = any(marker in user_message for marker in _BOUNDARY_MARKERS)
    candidate = by_id.get(resume_thread_id or "")
    if (
        candidate is not None
        and candidate.status is OpenThreadStatus.open
        and not postponed
        and not boundary
        and not signals.asks_for_clarification
        and not signals.user_disengagement
        and not signals.topic_shift
    ):
        candidate.last_touched_turn = turn_number
        result.resumed = candidate
        if candidate.id not in result.touched:
            result.touched.append(candidate.id)

    state.open_threads = _bounded_history(state.open_threads)
    return result


def _safe_text(value: str, limit: int) -> str:
    text = " ".join(_SAFE_TEXT.sub("", value).split()).strip()[:limit]
    lowered = text.casefold()
    if any(marker in lowered for marker in _INTERNAL_MARKERS):
        return ""
    return text


def _duplicate(state: ConversationState, topic: str) -> bool:
    normalized = topic.casefold().replace(" ", "")
    for item in active_threads(state):
        other = item.topic.casefold().replace(" ", "")
        if normalized in other or other in normalized:
            return True
        if SequenceMatcher(None, normalized, other).ratio() >= 0.8:
            return True
    return False


def _make_room(state: ConversationState, result: ThreadApplicationResult) -> None:
    active = active_threads(state)
    if len(active) < MAX_ACTIVE_THREADS:
        return
    victim = min(active, key=lambda item: (item.priority, item.last_touched_turn, item.created_turn))
    victim.status = OpenThreadStatus.resolved
    result.resolved.append(victim.id)


def _most_recent_active(state: ConversationState) -> OpenThread | None:
    active = active_threads(state)
    return max(active, key=lambda item: item.last_touched_turn) if active else None


def _next_id(state: ConversationState, turn_number: int) -> str:
    prefix = f"thread_{turn_number}_"
    used = {item.id for item in state.open_threads}
    index = 1
    while f"{prefix}{index}" in used:
        index += 1
    return f"{prefix}{index}"


def _bounded_history(threads: list[OpenThread]) -> list[OpenThread]:
    resolved = [item for item in threads if item.status is OpenThreadStatus.resolved]
    return active_threads(ConversationState(
        conversation_id="_", role_id="_", open_threads=threads
    )) + sorted(resolved, key=lambda item: -item.last_touched_turn)[:10]
