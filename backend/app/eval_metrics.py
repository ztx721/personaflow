"""Soft, deterministic metrics for visible human-likeness evaluation only."""

from __future__ import annotations


_OPENING_FILLERS = ("唔", "嗯", "啊", "哈哈", "……", "...")


def reply_opening_filler(reply: str) -> str | None:
    value = reply.lstrip(" \t\r\n\"'“‘（(")
    return next((filler for filler in _OPENING_FILLERS if value.startswith(filler)), None)


def analyze_opening_repetition(replies: list[str]) -> dict[str, object]:
    openings = [reply_opening_filler(reply) for reply in replies]
    filler_count = sum(opening is not None for opening in openings)
    repeated_count = 0
    longest_streak = 0
    current_streak = 0
    previous: str | None = None
    for opening in openings:
        if opening is not None and opening == previous:
            current_streak += 1
            repeated_count += 1
        elif opening is not None:
            current_streak = 1
        else:
            current_streak = 0
        longest_streak = max(longest_streak, current_streak)
        previous = opening
    return {
        "repeated_opening_count": repeated_count,
        "longest_identical_opening_streak": longest_streak,
        "filler_count": filler_count,
        "filler_frequency": filler_count / len(replies) if replies else 0.0,
    }


_EMOTION = ("累", "烦", "难受", "不开心", "心情", "压力", "委屈", "难过")
_ADVICE = ("应该", "不如", "试试", "休息", "歇一歇", "放松", "早点睡", "出去走走")
_EMPATHY = ("辛苦", "难受", "不容易", "太累", "太烦", "心疼")
_REASSURANCE = ("会好起来", "没关系", "你已经很好", "不是你的错")
_INVITATION = ("可以跟我说", "想说的话", "愿意的话", "要不要聊", "随时找我")
_COMPANION = (
    "我陪着你", "我一直在", "我会听你说", "我就在旁边", "陪你安静",
    "我就在这儿听", "随时都可以跟我说",
)
_PROXIMITY = (
    "给你倒杯", "坐你旁边", "靠在我", "陪你回去", "在这儿歇",
    "想翻书就翻书", "需要什么就叫我",
)
_BOUNDARY = ("算了", "不想说", "别问了", "不提了", "先这样")


_SERVICE_OFFER = ("我可以尽量回答", "有什么想知道的都可以问我", "我可以帮你")
_SELF_SUMMARY = ("其实都是些", "其实也就是些", "总之我就是这样的人")


def analyze_visible_reply(user_text: str, reply: str) -> dict[str, object]:
    emotional = any(marker in user_text for marker in _EMOTION)
    asks_advice = any(marker in user_text for marker in ("怎么办", "怎么做", "建议", "该不该"))
    question = "?" in reply or "？" in reply
    categories = {
        "empathy": any(marker in reply for marker in _EMPATHY),
        "advice": any(marker in reply for marker in _ADVICE),
        "reassurance": any(marker in reply for marker in _REASSURANCE),
        "invitation": any(marker in reply for marker in _INVITATION),
        "question": question,
    }
    move_count = sum(categories.values())
    companion = any(marker in reply for marker in (*_COMPANION, *_PROXIMITY))
    boundary = any(marker in user_text for marker in _BOUNDARY)
    restart = boundary and (question or categories["invitation"] or any(
        marker in reply for marker in ("聊聊别的", "看看书", "做点", "出去")
    ))
    return {
        "over_complete": emotional and move_count >= 3,
        "move_count": move_count,
        "advice_without_request": emotional and categories["advice"] and not asks_advice,
        "companion_language": companion,
        "boundary_restart": restart,
        "question": question,
        "assistant_offer": any(marker in reply for marker in _SERVICE_OFFER),
        "self_summary": any(marker in reply for marker in _SELF_SUMMARY),
    }
