# Mio settings and interface workflow

This local integration uses the shared Python environment. GitHub has not been updated.

## Clipboard and scrolling

Select chat text and use Ctrl+C, or right-click and choose Copy. Ctrl+A selects all text in that area. The chat history remains read-only. Paste into the message box with Ctrl+V or its context menu, then press Send or Ctrl+Enter. Enter inserts a line break. Typed input follows facial access and mode rules; it never invents a voice identity. Start Mio before sending. Messages may wait for the current voice output to finish.

The mouse wheel scrolls the area under the pointer. Short fields pass scrolling to the surrounding options form; long text fields scroll their own content. Lists and chat history support the same behavior.

## Settings pages

- Mio — Main settings: audio input, appearance, detection, mode and language controls.
- Mio — Texts: personality prompts, automatic replies, language instructions and recognition wording.
- Mio — Timings: main runtime and mode confirmation delays, edited through views of their original files.
- A separate page for Language model, Whisper, Piper, Melo, Voice changer, Agent DVR, CodeProject.AI, SpeechBrain, Vosk, Silero VAD, WebRTC, Vector memory and MicroBoost.
- Startup: the shared interpreter, model resources, external programs and desktop utilities.

Each module page groups its existing editable files, endpoint and optional executable launch settings when supported. Modules with no editable settings file show a notice directing configuration to their own app. This organization does not turn the internal audio helpers into standalone external services or invent unsupported controls.

## Reload Mio

Save the edited section first. Reload Mio appears only on Mio settings pages. It requests orderly shutdown of the dialogue engine, waits for exit, and starts that engine again. Vosk keywords, Silero and WebRTC audio helpers are restarted with Mio. LM Studio and its model, Whisper, Piper, Melo, RVC, Agent DVR, CodeProject.AI, SpeechBrain and MicroBoost are not restarted by this button. Window appearance still requires reopening the interface.

Displayed history is retained; the restarted engine begins a new in-memory conversation. Persistent memory is retained. Reload may interrupt a current reply. A timeout reports failure instead of stopping all services. The X still performs full shutdown according to the selected startup mode. External module changes require the affected module's own restart; Reload Mio does not apply server-side settings to untouched servers.

The new interface and engine input channel need one complete close/reopen to take effect. Subsequent changes to Mio prompts and timings can use Reload Mio.

The interface and settings pages were checked without starting services. Live conversation and service lifecycle validation remain pending; see INSTALLATION.txt.

## Typed author selection
Choose a registered person beside Type your message (green is selected). Send displays the message immediately under that person's name. The engine validates the profile and tells Mio that the person is writing in chat; it does not claim voice recognition. Facial access and existing mode priorities still apply. Drag over message text to select it, use Ctrl+C or right-click Copy, and paste into the input box. Selection stays visible after a refresh.
