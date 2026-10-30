# Source update — 30 October 2026

## Implemented in source

- Optional modules: microphone input, speaker recognition, face recognition, speech output, voice changer and vector memory. Changing local modules restarts the session through the portable launcher.
- Microphone selection, raw input level meter, thresholds and Test/Stop. MicroBoost is optional; a test closes only the MicroBoost process it started.
- Separate GPT and Gemini settings, enable switches, masked API keys, model help and API connection check. Local voice is the default; provider voice is optional, with the voice changer still available when enabled.
- Provider switching while awake, provider state/name display, spoken switch announcements, common Stop cancellation and local-only wake from sleep. Sleep commands are ignored during assistant speech.
- Child and Adult modes apply only to local Mio. Online providers use independent generic prompts and transient histories. No automatic export of local prompts, identities or vector memory.
- Whisper stops accepting additional utterances after one phrase is finalized and remains blocked during assistant speech; Vosk commands remain available.
- Compact, selectable chat with Windows clipboard support, full-width message backgrounds, follow-latest scrolling and clickable web sources. Technical errors go to logs; the chat shows `wakaranaii`.

## Clean defaults and privacy

English commands and generic User/Child/Adult profiles are retained. Initial memory is empty and no voices are enrolled. Online providers are disabled with blank model IDs and no stored keys. Voice input, speech output and local memory are enabled; face/speaker recognition and voice changer are disabled until configured.

Keys entered in the UI use Windows Credential Manager with a namespace specific to the installation path. Explicit API-key environment variables are also supported. Configure external applications and devices for the target machine. Public author credits, Patreon and Ko-fi links are intentionally preserved.

When an online provider is enabled, the text submitted by the user and that provider's temporary conversation history are sent to it. Do not include private information in those messages if it should remain local.

## Verification and remaining work

Python and JSON syntax were inspected, together with portable paths, settings projections and known private identifier/credential patterns in publication candidate files. No runtime data folder, chat logs or memory database is included. This is not a guarantee against every possible identifier and does not audit old Git history or image contents.

Live audio, provider calls, microphone hardware, full installation and shutdown have not been retested for this clean port. Validate those workflows before a release. The portable launcher is intentionally retained instead of prototype-specific launch scripts.

The existing FR/EN EXEs and Google Drive downloads have NOT been rebuilt or updated by this source change. Older test installers retain previously authorized external-service connections and must not be described as this new anonymous release. Rebuild and audit both packages separately before publishing them. No Git commit or push is included in this update.
