"""Check generated text before any part of it is queued for speech."""
import json
import re
import logging
from pathlib import Path

from langid.langid import LanguageIdentifier, model


class ResponseLanguageGuard:
    def __init__(self):
        self.config = json.loads((Path(__file__).resolve().parent.parent / "MainApp" / "config" / "langues_reponse.json")
                                 .read_text(encoding="utf-8-sig"))
        self.allowed = set(self.config["allowed"])
        self.terms = {term.casefold() for term in self.config["isolated_terms"]}
        self.forbidden_german_words = {
            word.casefold() for word in self.config.get("forbidden_german_words", [])
        }
        # Keep all detector languages: restricting it to allowed languages would
        # force Spanish and other forbidden languages into an allowed label.
        self.detector = LanguageIdentifier.from_modelstring(model, norm_probs=True)

    def latin_language(self, text, fallback="English"):
        """Choose a Latin voice without assigning a short English span to JP."""
        for name in self.config.get("proper_names", []):
            text = re.sub(re.escape(name), " ", text, flags=re.IGNORECASE)
        words = set(re.findall(r"[^\W\d_]+", text.casefold()))
        markers = self.config.get("latin_language_markers", {})
        votes = {code: len(words & set(markers.get(code, []))) for code in ("fr", "en")}
        if votes["fr"] != votes["en"]:
            return "French" if votes["fr"] > votes["en"] else "English"
        if sum(c.isalpha() for c in text) >= self.config["short_detection_letters"]:
            language, confidence = self.detector.classify(text)
            if language in {"fr", "en"} and confidence >= self.config["min_rejection_confidence"]:
                return {"fr": "French", "en": "English"}[language]
        return fallback if fallback in {"French", "English"} else "English"

    def rejected_language(self, text, target_language=None, french_only=False, mode=None):
        # Ingredient lines and short headings need their surrounding context.
        # A line such as "2 œufs" must never veto an otherwise French recipe.
        japanese_pattern = r"[\u3040-\u30ff\u3400-\u9fff]+"
        mode = "Child" if french_only else (mode or "Normal")
        allowed = set(self.config["mode_allowed"][mode])
        if "ja" not in allowed:
            for name in self.config.get("french_only_allowed_names", []):
                text = text.replace(name, "")
        if "ja" not in allowed and re.search(japanese_pattern, text):
            return "ja"
        if re.search(r"[\u0400-\u052f\u0600-\u06ff\uac00-\ud7af]", text):
            return "unsupported_script"
        contexts = [re.sub(japanese_pattern, " ", text),
                    "".join(re.findall(japanese_pattern, text))]
        # Also inspect substantial sentences, so one allowed paragraph does not
        # automatically authorize another paragraph in a forbidden language.
        for sentence in re.split(r"[!?。！？;；]+|(?<!\d)\.(?!\d)", text):
            contexts.extend([re.sub(japanese_pattern, " ", sentence),
                             "".join(re.findall(japanese_pattern, sentence))])
        seen = set()
        for context in contexts:
            for name in self.config.get("proper_names", []):
                context = re.sub(re.escape(name), " ", context, flags=re.IGNORECASE)
            letters = " ".join(re.findall(r"[^\W\d_]+", context, flags=re.UNICODE))
            if letters in seen or not letters or letters.casefold() in self.terms:
                continue
            seen.add(letters)
            words = {word.casefold() for word in letters.split()}
            if words & self.forbidden_german_words:
                logging.warning("Language filter: German marker in passage=%r", letters[:240])
                return "de"
            if mode == "Child" and not re.search(japanese_pattern, letters):
                child_language = self.config.get("child_language", "English")
                detected = self.latin_language(letters, child_language)
                detected_code = {"English": "en", "French": "fr"}.get(detected)
                if detected_code and detected_code not in allowed:
                    return detected_code
            minimum = self.config["short_detection_letters"] if mode == "Child" else self.config["min_detection_letters"]
            if sum(char.isalpha() for char in letters) < minimum:
                continue  # Ambiguous short text is assessed through its full context above.
            language, confidence = self.detector.classify(letters)
            if language not in allowed and confidence >= self.config["min_rejection_confidence"]:
                logging.warning("Language filter: %s, confidence %.1f%%, evaluated passage=%r",
                                language, confidence * 100, letters[:240])
                return language
        return None
