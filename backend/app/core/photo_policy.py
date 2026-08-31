"""Deterministic persona policy for trusted photo/media actions."""

from __future__ import annotations

from ..schemas import (
    AssetSpec,
    Emotion,
    EmotionGuidance,
    EmotionIntensityBand,
    PersonaPhotoPolicy,
    PhotoAction,
    PhotoCategory,
    PhotoPolicyDecision,
    RelationshipBand,
    RelationshipGuidance,
)

_CANCEL_MARKERS = ("算了", "不看了", "先别发", "以后再看", "不用了")
_SELFIE_MARKERS = ("自拍", "你本人", "你自己的照片", "你的照片", "本人照片")
_PERSONAL_MARKERS = ("生活照", "私照", "私人照片", "个人照片")
_RELATIONSHIP_RANK = {"low": 0, "medium": 1, "high": 2}


def classify_photo_category(
    proposed: PhotoCategory,
    user_message: str,
    candidate: AssetSpec | None,
) -> PhotoCategory:
    if any(marker in user_message for marker in _SELFIE_MARKERS):
        return PhotoCategory.selfie
    if any(marker in user_message for marker in _PERSONAL_MARKERS):
        return PhotoCategory.personal
    if candidate is None:
        return proposed
    values = {item.casefold() for item in [*candidate.tags, *candidate.topics]}
    for category, markers in (
        (PhotoCategory.bookstore, {"bookstore", "storefront", "shelves"}),
        (PhotoCategory.book, {"book", "history", "literature", "novel", "song_dynasty"}),
        (PhotoCategory.coffee, {"coffee", "drink"}),
        (PhotoCategory.cat, {"cat", "pet"}),
        (PhotoCategory.food, {"food", "meal", "dish"}),
        (PhotoCategory.travel, {"travel", "beach", "seaside", "bay"}),
    ):
        if values & markers:
            return category
    return PhotoCategory.public_object


def normalize_photo_action(
    proposed: PhotoAction,
    proposed_category: PhotoCategory,
    explicit_request: bool,
    user_message: str,
    candidate: AssetSpec | None,
    policy: PersonaPhotoPolicy,
    relationship: RelationshipGuidance,
    emotion: EmotionGuidance,
    story_authorized: bool = False,
) -> PhotoPolicyDecision:
    category = classify_photo_category(proposed_category, user_message, candidate)
    candidate_id = candidate.id if candidate is not None else None

    if any(marker in user_message for marker in _CANCEL_MARKERS):
        return _decision(proposed, PhotoAction.none, category, "cancelled_by_user", candidate_id)
    if not explicit_request and not story_authorized:
        approved = PhotoAction.offer if proposed is PhotoAction.offer else PhotoAction.none
        reason = "voluntary_offer" if approved is PhotoAction.offer else "no_explicit_request"
        return _decision(proposed, approved, category, reason, candidate_id)
    if story_authorized:
        approved = policy.story_offer_action
        reason = "approved_story_offer"
    elif (
        category in {PhotoCategory.personal, PhotoCategory.selfie}
        and relationship.band is RelationshipBand.high
        and proposed in {PhotoAction.none, PhotoAction.delay, PhotoAction.refuse}
    ):
        approved = policy.close_request
        reason = "close_relationship_policy"
    elif proposed in {PhotoAction.none, PhotoAction.offer, PhotoAction.delay, PhotoAction.refuse}:
        reason = {
            PhotoAction.none: "planner_declined",
            PhotoAction.offer: "offer_without_send",
            PhotoAction.delay: "planner_delayed",
            PhotoAction.refuse: "planner_refused",
        }[proposed]
        return _decision(proposed, proposed, category, reason, candidate_id)
    else:
        category_policy = policy.categories.get(category)
        if category_policy is None:
            approved = policy.stranger_request
            reason = "category_not_configured"
        elif _RELATIONSHIP_RANK[relationship.band.value] < _RELATIONSHIP_RANK[
            category_policy.min_relationship
        ]:
            approved = (
                policy.stranger_request
                if relationship.band is RelationshipBand.low
                else policy.familiar_request
            )
            reason = "relationship_below_minimum"
        else:
            approved = category_policy.default_action
            reason = "persona_policy_approved"

    if category in {PhotoCategory.personal, PhotoCategory.selfie}:
        if emotion.emotion in {Emotion.shy, Emotion.embarrassed}:
            approved, reason = PhotoAction.delay, "delayed_shy"
        elif (
            emotion.emotion is Emotion.angry
            and emotion.intensity_band is EmotionIntensityBand.high
        ):
            approved, reason = PhotoAction.refuse, "refused_angry"

    if approved is PhotoAction.send and candidate is None:
        approved, reason = PhotoAction.delay, "missing_trusted_asset"
    elif approved is PhotoAction.send and candidate.story_locked and not story_authorized:
        approved, reason = PhotoAction.delay, "blocked_story_lock"

    return PhotoPolicyDecision(
        proposed=proposed,
        approved=approved,
        category=category,
        adjusted=approved is not proposed,
        reason=reason,
        asset_candidate=candidate_id,
        asset_sent=approved is PhotoAction.send and candidate is not None,
    )


def _decision(
    proposed: PhotoAction,
    approved: PhotoAction,
    category: PhotoCategory,
    reason: str,
    candidate: str | None,
) -> PhotoPolicyDecision:
    return PhotoPolicyDecision(
        proposed=proposed,
        approved=approved,
        category=category,
        adjusted=approved is not proposed,
        reason=reason,
        asset_candidate=candidate,
        asset_sent=False,
    )
