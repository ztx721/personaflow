"""Conservative request-time timing policy for latent story progression."""

from __future__ import annotations

from ..schemas import (
    ConversationSignals,
    EmotionalCue,
    EmotionGuidance,
    OpenThread,
    SocialAction,
    StoryOpportunity,
    StoryPressure,
    StoryPressureDecision,
    Transition,
)


def normalize_story_pressure(
    proposed: StoryPressure,
    signals: ConversationSignals,
    social_action: SocialAction,
    emotion_guidance: EmotionGuidance,
    active_threads: list[OpenThread],
    resumed_thread: OpenThread | None,
    user_message: str,
    transition: Transition | None,
    story_active: bool,
) -> StoryPressureDecision:
    """Approve timing only; transition legality remains StoryEngine-owned."""
    if not story_active:
        return _blocked(proposed, "story_inactive")
    if transition is None:
        return _blocked(proposed, "no_candidate_transition")

    natural_match = next(
        (keyword for keyword in transition.when if keyword and keyword in user_message),
        None,
    )
    if signals.user_disengagement:
        return _blocked(proposed, "suppressed_user_boundary", transition.hint)
    if signals.asks_for_clarification:
        return _blocked(proposed, "suppressed_clarification", transition.hint)
    if signals.emotional_cue is EmotionalCue.negative or social_action is SocialAction.comfort:
        return _blocked(proposed, "suppressed_emotional_priority", transition.hint)
    if signals.minimal_acknowledgement:
        return _blocked(proposed, "suppressed_minimal_ack", transition.hint)
    if resumed_thread is not None:
        return _blocked(proposed, "suppressed_open_thread_callback", transition.hint)
    if active_threads and natural_match is None:
        return _blocked(proposed, "suppressed_active_open_thread", transition.hint)
    if signals.asks_direct_question and natural_match is None:
        return _blocked(proposed, "suppressed_direct_question", transition.hint)
    if signals.topic_shift and natural_match is None:
        return _blocked(proposed, "suppressed_topic_switch", transition.hint)
    if proposed is StoryPressure.none:
        return _blocked(proposed, "planner_declined_opportunity", transition.hint)

    # Current V2 story is opportunistic. Even a stronger proposal is capped at
    # active; exact matching needs no more than opportunistic pressure.
    approved = StoryPressure.opportunistic if natural_match else min(
        proposed, StoryPressure.active
    )
    reason = "natural_topic_match" if natural_match else "natural_story_opening"
    opportunity = StoryOpportunity(
        eligible=True,
        pressure=approved,
        natural_trigger=natural_match or "semantic_match",
        candidate_transition=transition.hint or None,
    )
    return StoryPressureDecision(
        proposed=proposed,
        approved=approved,
        adjusted=approved != proposed,
        reason=reason,
        opportunity=opportunity,
    )


def _blocked(
    proposed: StoryPressure,
    reason: str,
    candidate: str | None = None,
) -> StoryPressureDecision:
    return StoryPressureDecision(
        proposed=proposed,
        approved=StoryPressure.none,
        adjusted=proposed is not StoryPressure.none,
        reason=reason,
        opportunity=StoryOpportunity(
            eligible=False,
            pressure=StoryPressure.none,
            blocked_reason=reason,
            candidate_transition=candidate or None,
        ),
    )
