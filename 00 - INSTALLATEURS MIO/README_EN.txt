MIO — WINDOWS FR / EN INSTALLERS — 30 OCTOBER 2026
=================================================

IMPLEMENTED
-----------
- Standalone EXE: choose an empty folder, install, then Close and start Mio.
- Mio artwork and icon, shortcuts and graphical uninstaller with confirmation.
- Latest clean source: compact selectable chat, Windows clipboard, follow-latest
  scrolling, speaker names and provider status; technical errors stay in Logs.
- Individual module switches, microphone selection, level meter and Test/Stop.
  MicroBoost is optional; Stop closes only the instance started by that test.
- Separate GPT/Gemini settings, enable switches, masked API-key entry, connection
  check, model selection, local/provider voice and supported web search.
- Awake provider switching and shared Stop. Whisper is blocked during replies
  and after a first phrase is finalized, while Vosk commands remain available.
- Generic User/Child/Adult/Mio profiles, empty initial memory, no voice recordings
  or API keys. Family modes and automatic memory recall apply only locally.

REMAINING VALIDATION
--------------------
- Real installation and full microphone/voice/shutdown/external application/API
  workflow on the target PC. Package checks do not establish end-to-end operation.
- Complete single-GPU operation and a simpler first-run configuration flow.
- Full French localization: FR/EN means Vosk voice commands. Interface, prompts
  and generic automatic replies currently remain English.

INSTALLED
---------
Mio interface and engine, its internal Whisper/Vosk/Piper/Melo/vector-memory/
voice-recognition/VAD/echo-cancellation components and available internal models.
A shared Python environment is created. Python 3.11 may be installed for the
current user if missing; dependencies are downloaded. Internet and free disk
space are required.

NOT INSTALLED
-------------
LM Studio and its LLM weights, Agent DVR, CodeProject.AI, RVC/Voice Changer and
its models, MicroBoost, VB-CABLE, ANIMATE, avatars, drivers or API accounts/keys.
External applications and their data stay separate from Mio.

SIMPLE USER GUIDE
=================

1. PREPARE
64-bit Windows, NVIDIA GPU and a driver compatible with the CUDA dependencies.
For fully local operation, one 24 GB GPU or two 12 GB GPUs are recommended targets.
LLM size and context affect memory requirements; two 12 GB cards do not
necessarily provide one shared 24 GB memory space.
Initial settings use GPU 0 for services and GPU 1 for the LLM. For one GPU,
Language model > Local model loading: mainGpu=0, disabledGpus=[].
Keep services_gpu="0" in Startup. Full single-card operation remains to validate.

2. INSTALL
Run Mio Setup FR Test.exe for French voice commands or EN for English.
Only the EXE is required; no neighboring payload directory is needed.
Choose an empty dedicated installation folder. Existing installs are preserved.
Wait for downloads and checks. If setup fails, read data\logs\installation.log
inside the folder you selected.

3. CONFIGURE
Open Mio and Customize. Defaults are generic; no private development-machine
paths are included. Configure external programs/devices before pressing Start.
Connect LM Studio, install its LLM separately and use the same model identifier
in the connection and local model loading pages.
Mio — Modules selects features. Defaults: microphone, local speech and memory on;
face recognition, speaker identification and RVC off. No camera is initially required.
Microphone selects the Windows default or an input device. Use Test, check levels,
then Stop. Optional MicroBoost and VB-CABLE may help gain after separate setup.
Enable face recognition or RVC only after connecting the external applications.
Save stores settings; Reload applies them. Local module changes restart the session.

4. USE
Press Start, then wake Mio: "wake up Mio" (EN) or "reveille toi Mio" (FR).
Controls shows the configured commands. Choose a speaker before sending typed
text. Ctrl+Enter sends; Enter adds a line.
Stop cancels the exchange without changing provider. After sleep, wake local Mio
before switching again. Do not run FR and EN simultaneously: they share ports.

5. OPTIONAL GPT / GEMINI
Online — GPT or Online — Gemini: enter a model ID available to your account,
save your own API key, test the connection, then enable the provider.
The connection check does not validate a complete text/voice conversation.
Local voice is the default. Provider voice also needs its speech model and voice
name; the configured voice changer remains applicable when enabled.
While awake, say "Are you there GPT / Gemini / Mio" in EN. In FR use "T'es la
GPT", "T'es la Gemini" or "T'es la Mio". Edit these in Online — Commands.
Recognition depends on the Vosk vocabulary.
Keys are not bundled; keys entered in the UI use installation-specific Windows
Credential Manager entries and are masked in the field.
Providers receive your message and their temporary conversation history. Local
profiles, family prompts and vector memories are not automatically exported.
Pricing, quotas and available models depend on the provider/account.

6. CLOSE / UNINSTALL
Close Mio with X. Starting/stopping external Windows services may require an
administrator confirmation each time; no permanent authorization is added.
Open Uninstall Mio from Start, verify its folder and confirm. Local files/data
are removed; external applications remain. Close running components first.
If you saved an API key, remove it in its API settings page before uninstalling.

The maintainer confirmed uploading both latest EXEs to the Google Drive folder
linked in the GitHub README. Compare their SHA-256 values with SHA256SUMS.txt
to identify this release; a full hosted-file download comparison remains pending.
