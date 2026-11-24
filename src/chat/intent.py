"""Small on-device intent rules for spoken Reachy commands."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher


_TEXT_CLEANUP = re.compile(r"[^a-z0-9'\u3400-\u9fff]+")
_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_LATIN_WAKEWORDS = {"reachy", "reechy", "reachi", "reachie", "richie", "ritchie"}
_CHINESE_WAKEWORDS = ("瑞奇", "瑞琪", "睿奇")
_SLEEP_WORDS = {
    "bedtime",
    "break",
    "breather",
    "nap",
    "pause",
    "relax",
    "rest",
    "quiet",
    "sleep",
    "standby",
    "stop",
    "wait",
}
_SLEEP_PHRASES = (
    "call it a day",
    "go to bed",
    "go to sleep",
    "have a break",
    "have a rest",
    "lie down",
    "power down",
    "power off",
    "shut down",
    "take a break",
    "take a breather",
    "take a nap",
    "take a rest",
    "take five",
    "wind down",
    "wait a bit",
    "wait a minute",
    "wait a moment",
    "hold on",
    "give me a minute",
    "give me a moment",
    "take some time off",
    "time off",
    "that's enough for now",
    "that's all",
    "i'm done for now",
    "we're done for now",
)
_CHINESE_SLEEP_CUES = (
    "休息",
    "歇一下",
    "歇一歇",
    "歇一会",
    "歇会",
    "歇会儿",
    "睡",
    "暂停",
    "停一下",
    "停一会",
    "停会儿",
    "待机",
    "休眠",
    "安静",
    "放松",
    "收起来",
    "歇一歇",
    "缓一缓",
    "先停",
)
_ENGLISH_NEGATIONS = {
    "can't",
    "cannot",
    "don't",
    "never",
    "not",
    "shouldn't",
    "won't",
}
_CHINESE_NEGATION_ENDINGS = (
    "不要再",
    "不能再",
    "不想再",
    "先不要",
    "先别",
    "别再",
    "不要",
    "不必",
    "不能",
    "不想",
    "不愿",
    "不应",
    "不该",
    "不去",
    "不需要",
    "不用",
    "不会",
    "无需",
    "别",
    "不",
)
_CHINESE_AFFIRMATIVE_QUESTIONS = ("要不要", "是不是该", "该不该", "为什么不", "为何不")


def _normalise(text: str) -> str:
    """规范化转写文字，统一大小写并去除标点差异。

    Normalize transcript text, case, and punctuation differences.
    """
    text = unicodedata.normalize("NFKC", text).casefold()
    return _TEXT_CLEANUP.sub(" ", text).strip()


def _wakeword_end(text: str) -> int | None:
    """查找 Reachy 唤醒词的位置，并容忍常见的转写拼写变体。

    Find the Reachy wake-word position while allowing common transcript variants.
    """
    candidates: list[int] = []
    for match in _WORD.finditer(text):
        token = match.group()
        if token in _LATIN_WAKEWORDS:
            candidates.append(match.end())
        elif len(token) >= 6 and max(
            SequenceMatcher(None, token, alias).ratio()
            for alias in _LATIN_WAKEWORDS
        ) >= 0.80:
            candidates.append(match.end())

    for alias in _CHINESE_WAKEWORDS:
        position = text.find(alias)
        if position >= 0:
            candidates.append(position + len(alias))

    return min(candidates) if candidates else None


def _is_negated(text: str, cue_start: int) -> bool:
    """忽略紧邻否定词的休息意图，避免“不要休息”触发。

    Ignore sleep cues preceded by nearby negation, such as “do not rest”.
    """
    prefix = text[:cue_start]
    previous_words = [match.group() for match in _WORD.finditer(prefix)][-5:]
    if re.search(r"(?:^|\s)why don't you(?:\s|$)|(?:^|\s)why not(?:\s|$)", prefix):
        return False
    if any(word in _ENGLISH_NEGATIONS for word in previous_words):
        return True

    chinese_prefix = prefix[-12:]
    if any(question in chinese_prefix for question in _CHINESE_AFFIRMATIVE_QUESTIONS):
        return False
    return any(chinese_prefix.endswith(ending) for ending in _CHINESE_NEGATION_ENDINGS)


class LocalIntentDetector:
    """在 Reachy 本机识别带唤醒词的休息或暂停指令。

    Detect wake-word-prefixed rest and pause commands locally on Reachy.
    """

    def is_sleep_command(self, transcript: str) -> bool:
        """判断转写是否表达了让 Reachy 休息、暂停或进入待机的意思。

        Check whether a transcript asks Reachy to rest, pause, or enter standby.
        """
        text = _normalise(transcript)
        wake_end = _wakeword_end(text)
        if wake_end is None:
            return False

        command = text[wake_end:].strip()
        if not command:
            return False

        cue_positions: list[int] = []
        for cue in _CHINESE_SLEEP_CUES:
            position = command.find(cue)
            if position >= 0:
                cue_positions.append(position)

        for phrase in _SLEEP_PHRASES:
            pattern = re.compile(
                rf"(?<![a-z0-9']){re.escape(phrase)}(?![a-z0-9'])"
            )
            cue_positions.extend(match.start() for match in pattern.finditer(command))

        for match in _WORD.finditer(command):
            token = match.group()
            if token in _SLEEP_WORDS:
                cue_positions.append(match.start())
            elif len(token) >= 4 and max(
                SequenceMatcher(None, token, cue).ratio() for cue in _SLEEP_WORDS
            ) >= 0.84:
                cue_positions.append(match.start())

        return any(not _is_negated(command, position) for position in cue_positions)
