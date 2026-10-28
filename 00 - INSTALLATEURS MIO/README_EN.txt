MIO — PROJECT STATUS AND INSTALLATION GUIDE
==========================================

ALREADY IMPLEMENTED
-------------------
- Two standalone EXE installers: French (FR) or English (EN) voice commands,
  with the corresponding Vosk model selected.
- Graphical installation into a chosen folder, shortcuts and a graphical
  uninstaller with confirmation. The menu entry is named Uninstall Mio.
- Chat interface, typed messages, author selection, clipboard support,
  scrolling and separate customization pages for each module.
- Internal components and their speech/recognition model files are bundled.
  The Python environment and dependencies are installed separately.
- Anonymized packages: empty initial memory, generic User, Child and Adult
  profiles, with no voice recordings or personal descriptions preloaded.
- Editable generic prompts and a rule to spell numerical values out in words.
- Reload Mio restarts the engine and its required helpers without reloading
  every external server. Technical application windows minimize after startup.
- Existing external connections and hardware settings retained for local testing.

STILL TO IMPLEMENT / VALIDATE
----------------------------
- Validate both anonymized installers on another PC, then check the full
  microphone, camera, recognition and reply workflow.
- Add guided single-GPU / dual-GPU selection and validate all services running
  together on one card. Current defaults target two GPUs.
- Complete French localization: FR currently means French voice commands;
  the interface and generic prompt text are currently in English.
- Add API-key entry, authentication and the necessary adapters for different
  hosted API providers.
- Simplify first-run configuration. External programs, devices and person
  enrollment still require configuration.


SIMPLE USER GUIDE
=================

1. PREPARE THE PC
-----------------
This build targets 64-bit Windows with an NVIDIA GPU and a driver compatible
with Mio's CUDA libraries. It does not provide a ready-to-use CPU or AMD mode.

Recommended target configurations for running everything locally:
- One GPU with 24 GB of VRAM: language model and services on the same card.
- Two GPUs with 12 GB of VRAM each: Mio services on one card and the language
  model on the other.

These guidelines do not guarantee that an arbitrary language model will fit.
Model size, quantization, context length and other services affect memory use.
Two 12 GB cards do not automatically act as one 24 GB card. Their memory remains
separate in the current configuration.

You need Internet access for Python dependencies, a microphone, audio output
and a camera for the current workflow with facial authorization. Allow enough
disk space for Mio, its environment and your chosen external models.

2. CHOOSE AND INSTALL MIO
------------------------
- French voice commands: run Mio Setup FR Test.exe.
- English voice commands: run Mio Setup EN Test.exe.

Each EXE contains its application package; no adjacent payload folder is needed.
Click Browse, choose an empty installation folder, then click Install Mio.
The default location is %LOCALAPPDATA%\Mio. A desktop shortcut is optional.

Wait for extraction and dependency installation to finish. The installer looks
for 64-bit Python 3.11 with Tkinter and attempts to install it if missing.
If that fails, install Python 3.11 with Tkinter and retry.
When installation completes, click Close and start Mio to open the chat.

3. CONNECT EXTERNAL PROGRAMS
---------------------------
The EXE installs Mio and its internal components, not these applications:
- LM Studio and your selected language model;
- Agent DVR and CodeProject.AI for camera and face recognition;
- VoiceChanger/RVC and its voice-conversion model;
- MicroBoost, Insta360 Link Controller, audio drivers and devices.

The current complete workflow expects its configured external services.
The paths retained in these test editions are not universal settings for every PC.

Open Customize:
- Language model: set the server addresses and an available model. Use the same
  identifier in Connection and model and Local model loading for the current
  local-loading workflow.
- Agent DVR camera, CodeProject.AI faces and Voice changer: check each service's
  URLs and program-launch settings.
- Startup > Interface runtime: check executables, working directories and
  resources. Disable startup utilities that you are not using.
- Mio — Main settings: check audio input/output. The configured virtual-audio
  cable routing must match the devices installed on your PC.

Save each page. A VRM avatar is optional and needs separate software:
this installer does not install an avatar or avatar application.

4. CHECK GPU ASSIGNMENT
-----------------------
Current defaults use GPU 0 for Mio services and GPU 1 for the language model.
Check that these indices refer to the intended cards.

To try one 24 GB GPU, open Language model > Local model loading, set mainGpu
to 0 and disabledGpus to [] (an empty list). Keep services_gpu as "0" in
Startup > Interface runtime. Choose a model that leaves enough VRAM for speech
services. This arrangement still needs validation with all services active.

5. CUSTOMIZE AND START
---------------------
- Mio — Texts: edit Prompt / Common, Normal, Adult or Child, automatic replies
  and language wording. Common applies to all three modes.
- Mio — Timings: adjust delays. Other pages group settings by module.
- SpeechBrain recognition: profiles have no voice samples. To identify a voice,
  add appropriate reference recordings and configure their paths. Register faces
  in the corresponding external service.

Click Save, return to the chat and click Start. Accept the Windows administrator
prompt when Agent DVR service control is requested. This does not grant a
permanent service permission.

Wake commands include "hey Mio" / "wake up Mio" in EN and
"reveille-toi Mio" / "yo Mio" in FR. "stop" interrupts a reply.
The configured commands are listed in Controls.

To type, choose User, Child or Adult, enter a message and click Send or press
Ctrl+Enter. Enter alone inserts a line break. Author selection does not bypass
facial authorization or identify a voice.

After changing prompts or timing, use Reload Mio on a Mio settings page.
An external server's own settings require that server's own restart.

6. EXTERNAL APIS: CURRENT CAPABILITIES
-------------------------------------
Some service addresses are configurable. A remote language-model server can
be connected if it exposes the expected request, streaming-response and health
formats without additional authentication. Disable automatic local LLM loading
and adapt the connection and launch settings for that arrangement. This is not
automatic support for arbitrary APIs.

API-key handling and hosted-provider adapters still need implementation.
These installers also still enforce local endpoints for bundled Whisper and TTS
services. Changing a URL therefore cannot replace every local module with a
remote API.

7. STOP, TROUBLESHOOT OR UNINSTALL
---------------------------------
Close Mio using the window's X button. Do not run the FR and EN editions at the
same time: they use the same ports. Logs opens the log view; log files are also
available under data\logs inside the installed folder.

For installation failures, read data\logs\installation.log. If the destination
already contains an installation, choose another empty folder or uninstall that
installation first.

To remove Mio, close the application, open Uninstall Mio from the Start menu
and confirm. This installation's local data is removed. External applications,
their models and their own data are retained.

Memory starts empty; Mio can subsequently retain new conversation information.
Anonymization applies to the package. Connected external services retain their
own data and may return their existing enrolled identities.
