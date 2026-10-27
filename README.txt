MIO
===

Mio is a local digital companion under development, coded by GPT with Yaban as software designer. It supports voice conversations and displays them in a chat window. This repository contains the application source and configuration examples.

How it works
------------
1. The audio services capture speech. WebRTC reduces echo, SileroVAD detects speech, and Vosk recognizes wake, stop, and sleep commands.
2. Whisper transcribes each utterance. The chat shows both provisional and final text.
3. Agent DVR and CodeProject.AI can report who is visible to the camera. SpeechBrain can identify voices after users create voice profiles. These signals select the conversation mode and provide context.
4. Vector memory retrieves relevant facts and stores useful new facts in the background.
5. Mio builds the conversation context for the active mode and calls a dialogue model served by LM Studio. Piper synthesizes French speech, while MeloTTS can handle other languages. VoiceChanger RVC can transform the output voice.
6. The chat interface shows status, transcriptions, replies, and errors. It opens before the services, provides customization controls, and starts the services on demand. Closing the window stops the processes launched by that session.

Repository layout
-----------------
src/          Component source code and configuration.
interface/    Desktop configuration and service controls.
scripts/      Shared Python environment setup, launch, and shutdown.
settings/     Configuration examples.
profiles/     Identity-free profile examples.
vendor/       Third-party source used by Mio.
env/          Local Python environment; recreate it on each machine.
cache/        Local dependency and model cache.
data/         Runtime databases, state, and logs.

Development setup
-----------------
Install Python 3.11 and create an environment in env, for example with py -3.11 -m venv env. Then run scripts/installer_env_unique.ps1 to install the dependencies listed in requirements-unified.txt.

Open interface/Launch Mio.vbs (or scripts/Start-Mio.ps1), select Customize, and configure your model paths, external applications and prompts. The launcher and interface code are together in the interface directory. Select Start to load the services. Reload to apply changes saves settings and restarts the session. Close the window with X to stop it. See USER-GUIDE.txt for details.

Agent DVR, CodeProject.AI, LM Studio and VoiceChanger RVC run as external applications. Already-running services are reused; executable paths can be configured for services Mio should start. Voice, transcription and dialogue models must be supplied separately under their respective licenses.

Mio is not yet packaged as an executable or installer. The complete startup flow and MeloTTS synthesis in the shared environment still need validation. Users can configure speaker identification, display names, and conversation modes for their installation.

Project language
----------------
English is the reference language for development, UI, prompts and default replies. Conversation languages remain configurable. Voice command recognition requires a matching Vosk model; the English defaults use vosk-model-small-en-us-0.15. See DEVELOPMENT.md for conventions.
