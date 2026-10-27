"""Exact probabilities of emitted text tokens, without modifying CTranslate2."""
import math
import ctranslate2
import numpy as np
import torch


class TokenConfidenceDecoder:
    def __init__(self, decoder, end_of_text_token):
        self.decoder = decoder
        self.end_of_text_token = end_of_text_token
        self.reset()

    def __getattr__(self, name):
        return getattr(self.decoder, name)

    def reset(self):
        self.last_values = []
        self.tokens = []
        self.probabilities = []
        self.cursor = 0
        self.probability_sum = 0.0
        self.token_count = 0

    def generate(self, *args, **kwargs):
        kwargs["beam_size"] = 1
        kwargs["return_logits_vocab"] = True
        results = self.decoder.generate(*args, **kwargs)
        if len(results) != 1:
            raise RuntimeError("Scoring expects one utterance per decoding pass")
        result = results[0]
        tokens = result.sequences_ids[0]
        if not result.logits or len(result.logits[0]) < len(tokens):
            raise RuntimeError("Individual token distributions missing")
        steps = [(token, logits) for token, logits in zip(tokens, result.logits[0])
                 if token < self.end_of_text_token]
        self.tokens = [token for token, _ in steps]
        self.probabilities = []
        self.cursor = 0
        for offset in range(0, len(steps), 32):
            batch = steps[offset:offset + 32]
            if all(isinstance(v, ctranslate2.StorageView)
                   and v.device in ("cuda", ctranslate2.Device.cuda) for _, v in batch):
                with torch.inference_mode():
                    logits = torch.stack([torch.as_tensor(v, device="cuda").reshape(-1)
                                          for _, v in batch]).float()
                    ids = torch.tensor([token for token, _ in batch], device="cuda")
                    values = torch.exp(logits.gather(1, ids[:, None]).squeeze(1)
                                       - torch.logsumexp(logits, dim=1)).tolist()
            else:
                values = []
                for token, logits in batch:
                    if isinstance(logits, ctranslate2.StorageView):
                        logits = logits.to_device(ctranslate2.Device.cpu)
                    logits = np.asarray(logits, dtype=np.float64).reshape(-1)
                    weights = np.exp(logits - np.max(logits))
                    values.append(float(weights[token] / weights.sum()))
            if any(not math.isfinite(p) or not 0 <= p <= 1 for p in values):
                raise RuntimeError("Invalid score distribution")
            self.probabilities.extend(values)
        return results

    def accept(self, emitted_tokens):
        """Only count tokens actually yielded, not discarded/no-speech windows."""
        tokens = [token for token in emitted_tokens if token < self.end_of_text_token]
        self.last_values = []
        if not tokens:
            return 0.0
        for start in range(self.cursor, len(self.tokens) - len(tokens) + 1):
            if self.tokens[start:start + len(tokens)] == tokens:
                values = self.probabilities[start:start + len(tokens)]
                self.last_values = list(values)
                self.cursor = start + len(tokens)
                self.probability_sum += sum(values)
                self.token_count += len(tokens)
                return sum(values) / len(values)
        raise RuntimeError("Transcribed tokens do not match decoder scores")

    def mean(self):
        return self.probability_sum / self.token_count if self.token_count else 0.0
