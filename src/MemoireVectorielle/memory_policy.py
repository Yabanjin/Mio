"""Conservative evidence checks; no speaker identification from voice tags."""
import re
import unicodedata


def normalized(text):
    return ' '.join(unicodedata.normalize('NFKC', str(text)).split()).casefold()


EPHEMERAL = re.compile(
    r"(?:qui.{0,20}(?:parle|te parle)|who.{0,20}(?:speaking|talking)|"
    r"(?:tu|vous) (?:m'entends|me comprends|m'entendez)|"
    r"(?:can|do) you (?:hear|understand) me|誰.{0,10}話して|聞こえますか)", re.I)
DEICTIC = re.compile(r"\b(?:je|j'|moi|mon|ma|mes|tu|toi|ton|ta|tes|nous|notre|i|my|me|you|your|we|our)\b|私|僕|あなた", re.I)
CORRECTION = re.compile(r"\b(?:corrige|correction|rectifie|rectification|en fait|actually|correct|correction|instead)\b|訂正|修正|正しく", re.I)
PROPERTY_MARKERS = {
    'birth_date': r"né|née|naissance|anniversaire|born|birth|誕生日|生まれ",
    'name': r"nom|prénom|appell|name|名前|呼ん",
    'hair_color': r"cheveu|hair|髪",
    'eye_color': r"yeux|œil|eyes?|瞳|目",
}


def mio_direct_description(fact):
    """Narrow lexical check; the extractor must also attest an unambiguous addressee."""
    value = normalized(fact)
    if re.search(r'[?？«»"“”]|\b(?:si|if|imagine|suppos|peut-être|maybe)\b', value):
        return False
    start = r"(?:(?:en fait|correction|actually)\s*[, :]*\s*)?"
    direct = re.match(start + r"(?:tu (?:es|as|portes|vis|fonctionnes|dois)\b|ton (?:avatar|apparence|corps|fonctionnement)\b|ta (?:nature|tenue|robe|voix)\b|tes (?:cheveux|yeux|vêtements)\b|you (?:are|have|wear|live)\b|your (?:avatar|appearance|hair|eyes|body|voice)\b|あなた(?:は|の))", value)
    description = re.search(r"machine|numérique|logiciel|ordinateur|écran|bureau|avatar|vrm|cheveu|yeux|œil|tenue|kimono|vêtement|robe|oreille|amie|fonctionn|digital|software|computer|screen|desktop|hair|eyes?|clothes|friend|機械|アバター|髪|目|友達", value)
    return bool(direct and description)


def evidence_state(fact, entity='', property_name='', durable=True, *, mio_addressee=False):
    """Returns a disposition, never a fabricated entity or rewritten fact."""
    if not durable:
        return 'review', 'durable statement not established'
    if EPHEMERAL.search(fact):
        return 'review', 'one-off question or check'
    addressed_mio = (mio_addressee and normalized(entity) == 'mio'
                     and property_name in {'identity', 'operation', 'hair_color', 'eye_color', 'other'}
                     and mio_direct_description(fact))
    if not addressed_mio and (not entity or len(entity) < 2 or DEICTIC.fullmatch(entity) or normalized(entity) not in normalized(fact)):
        return 'review', 'subject not explicit in the quote'
    if property_name not in {'birth_date', 'name', 'hair_color', 'eye_color',
                              'relationship', 'preference', 'identity', 'operation', 'other'}:
        return 'review', 'property not established'
    marker = PROPERTY_MARKERS.get(property_name)
    if marker and not re.search(marker, fact, re.I):
        return 'review', 'property unsupported by the quote'
    return 'active', 'stated description addressed to Mio; quote retained' if addressed_mio else ''


def legacy_state(fact):
    if EPHEMERAL.search(fact):
        return 'review', 'legacy one-off question'
    if DEICTIC.search(fact):
        return 'review', 'legacy quote with pronouns but no established subject'
    return 'legacy', 'legacy quote without detailed provenance'


def legacy_subject(fact):
    names = re.findall(r'\bMio\b|ミオ', fact, re.I)
    names = list(dict.fromkeys(names))
    properties = [key for key, marker in PROPERTY_MARKERS.items() if re.search(marker, fact, re.I)]
    return (names[0] if len(names) == 1 else '', properties[0] if len(properties) == 1 else '')


def entity_key(entity):
    return normalized(entity)
