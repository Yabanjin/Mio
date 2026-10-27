# Development conventions

Mio is under development, coded by GPT with Yaban as software designer.

## Project language

Use English for new and edited application UI, prompts, default replies, logs,
error messages, comments, docstrings, documentation and public descriptions.
Keep all user-facing text customizable. English is the default, not a claim that
every speech model supports every language.

Preserve language-specific parsing data, number pronunciation rules, proper names,
and third-party code and licenses in their original form. French and Japanese
language processing remains available. Do not translate user-entered memories.
The prompt modes are Normal, Child and Adult. The memory categories are Mio,
Family and Personal. Some internal resource filenames retain their historical
spelling; the configuration interface displays English labels.

## English defaults

Default spoken replies and commands are English. Child mode defaults to English;
its language and allowlist are configurable in langues_reponse.json. Normal mode
accepts English, French and Japanese; Adult mode accepts English and French.
Melo handles English and Japanese speech, while Piper handles French.

The English Vosk model is vosk-model-small-en-us-0.15, available under Apache 2.0:
https://alphacephei.com/vosk/models
Local models are not source files and remain outside Git tracking. Configure the
Vosk model path for each installation. No runtime services were started during
the English localization pass; end-to-end audio behavior remains to be checked.

## Interface entry point

The Windows launcher and startup script live alongside the interface code:
`interface/Launch Mio.vbs` and `interface/Open-Interface.ps1`.
`scripts/Start-Mio.ps1` delegates to that entry point. Paths resolve from the
project directory, so the interface folder must remain inside the full project.
