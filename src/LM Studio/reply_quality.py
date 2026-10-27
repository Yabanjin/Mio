"""Conservative checks for long copied replies, not for short acknowledgements."""
import re
import unicodedata
from difflib import SequenceMatcher


def words(text):
    value = unicodedata.normalize('NFKC', text).casefold()
    return re.findall(r'[\u3040-\u30ff\u4e00-\u9fff]|[^\W_]+', value)


def repetition_requested(text):
    value = unicodedata.normalize('NFKD', text.casefold())
    value = ''.join(c for c in value if not unicodedata.combining(c))
    if re.search(r"(?:ne|pas|arrete|stop|don't|do not).{0,30}(?:repet|redis|repeat)|(?:repet\w*|redis).{0,15}pas", value):
        return False
    return bool(re.search(r'\b(?:repete\w*|redis|redonne|repeat|poeme|poem)\b|say.{0,20}again|もう一度|繰り返', value))


def repetition_reason(reply, user_text, history):
    if repetition_requested(user_text):
        return ''
    current = words(reply)
    if len(current) < 20:
        return ''
    for entry in history:
        if entry.get('role') != 'assistant':
            continue
        previous = words(entry.get('content', ''))
        if len(previous) < 40:
            continue
        matcher = SequenceMatcher(None, previous, current, autojunk=False)
        copied = matcher.find_longest_match(0, len(previous), 0, len(current)).size
        if copied >= 12 and (copied >= len(current) * .5 or matcher.ratio() >= .8):
            return 'long passage copied from a previous reply'
    sentences = re.split(r'[.!?。！？]+\s*', reply.strip())
    starts = [tuple(words(sentence)[:3]) for sentence in sentences if len(words(sentence)) >= 4]
    if len(current) >= 70 and any(starts.count(prefix) >= 3 for prefix in set(starts)):
        return 'same opening repeated across multiple sentences'
    return ''
