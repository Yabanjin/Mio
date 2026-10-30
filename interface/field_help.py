"""English field guidance, kept separate from the user's configuration values."""
from pathlib import Path

HELP = {
 'voice_input': ('Microphone and speech-to-text input.', 'Off uses typed chat only. On uses the selected microphone, Whisper, Vosk commands, Silero and WebRTC together.', 'Off avoids starting this input chain and MicroBoost. Use typed Mio wake/Stop commands. Speaker identification is inactive too when no microphone is used. Apply with Restart with selected modules.'),
 'speaker_recognition': ('Identify who is speaking with SpeechBrain.', 'Off transcribes speech without assigning a speaker name. On uses enrolled speaker references when available.', 'This switch does not disable speech transcription. Typed author selection still works. Without facial or speaker identity, the normal family mode is used unless Child mode is already active.'),
 'face_recognition': ('Camera recognition and the facial access requirement.', 'Off permits dialogue without camera authorization. On requires the existing registered-face checks and timers.', 'Off avoids starting Agent DVR, face recognition and the camera controller. Face-based arrivals and family selection are inactive; selected chat authors and enabled speaker recognition can still select family modes.'),
 'speech_output': ('Read Mio replies aloud.', 'Off keeps replies as text only. On uses local speech for Mio, or online speech for the selected online provider.', 'Off avoids local speech-model and RVC startup and all speech synthesis calls. Stop still cancels response generation; Sleep applies immediately when no voice is needed.'),
 'voice_changer': ('Convert synthesized speech with RVC.', 'On keeps your Voice Changer for local Mio voices and GPT/Gemini API voices. Off plays the original synthesized voice.', 'Used only with speech output enabled. Both local and API synthesis pass through the same RVC conversion when enabled.'),
 'vector_memory': ('Local long-term memory recall and extraction.', 'Off disables memory recall and new memory extraction. On keeps the current memory behavior.', 'Existing memories are preserved. The local memory service is not started when disabled. Online conversations do not automatically use local vector memories.'),
 'enabled': ('Allow this online provider to be selected.', 'Enable only the providers you want to use. Both are disabled by default.', 'Disabling the active provider cancels its turn and returns to local. Enabling makes it available without sending a request. Model, voice and API key must still be configured. The main Services menu has the same switch.'),
 'gpt_wake_phrases': ('Commands selecting GPT during an awake session.', 'One full command per line, for example GPT reveille toi. Accents and punctuation are ignored.', 'Wake Mio first. A provider command cancels the old turn and changes online LLM and speech; existing Mio wake commands return to local.'),
 'gemini_wake_phrases': ('Commands selecting Gemini during an awake session.', 'One full command per line, for example Geminy reveille toi or Gemini reveille toi.', 'Wake Mio first. Commands must differ from every existing Mio command. Exact recognition is required; Stop keeps the selected provider.'),
 'llm_model': ('The language model generating the written reply.', 'Enter the exact API model ID shown by the provider. This is a model identifier, not your API key, a file path or the name of your subscription.', 'Selects the online reply model. Only the reply model ID and API key are needed when using the local Mio voice.'),
 'tts_source': ('Choose where this provider gets its spoken voice.', 'Local Mio voice uses Piper/Melo. Provider API voice uses this provider\'s speech model and voice; fill in the extra fields shown below.', 'Both choices pass through Voice Changer when enabled in Mio — Modules. Local is the default. Save, then Reload Mio to apply this choice.'),
 'tts_model': ('API speech model reading the accepted text aloud.', 'Enter a speech model API ID, separately from the reply model ID. Only needed for Provider API voice.', 'The provider synthesizes the text, then the local Voice Changer converts it when enabled. Automatic Stop and greeting replies retain local synthesis.'),
 'tts_voice': ('Voice selected at the online speech service.', 'Enter a voice supported by the chosen speech model, such as coral for OpenAI or Kore for Gemini; verify model availability in the provider documentation.', 'Changes the sound of future online replies. It does not install a local voice or change your RVC model.'),
 'web_search': ('Allow the online model to search for current information.', 'Enable for sourced web answers; disable to omit the search tool.', 'The provider decides when to search. Sources appear as clickable links. Search availability, quotas and charges depend on your model/account.'),
 'api_key_environment': ('Optional environment variable supplying the API key.', 'Enter only the variable NAME, such as OPENAI_API_KEY or GEMINI_API_KEY, never the key itself. Or use the masked key panel above.', 'The Windows saved key takes priority. Restart Mio after changing Windows environment variables. Saved keys stay outside project files.'),
 'provider_instruction': ('Additional instructions for this online provider.', 'Write the dedicated GPT or Gemini prompt here. The existing shared main and selected family prompts are added automatically.', 'These prompts and the current question/history for this provider and family mode are sent online. Local vector memories, camera context and recordings are not automatically sent. Family and language rules remain active.'),
 'use_custom_connections': ('Choose how services are started.', 'Off keeps the current local launchers. On uses the connection pages and optional programs below.', 'Custom mode does not install services or change their ports. Existing external servers are not stopped by Mio.'),
 'launch_with_mio': ('Start this program when you press Start in custom mode.', 'Enable only when Mio should launch it; leave off for an already running service.', 'Mio owns programs it starts and stops them when the session closes. Use a program that stays running rather than a launcher that immediately exits.'),
 'executable': ('Program to launch for this component.', r'Browse to an .exe, for example F:\Services\Speech\env\Scripts\python.exe. Do not put arguments here.', 'Used only when Launch with Mio is enabled in custom mode.'),
 'arguments': ('Arguments passed to that program.', 'Enter one argument per line, for example a Python script path, then --port, then 9000. Do not add surrounding quotes to paths.', 'Changes how the program starts. Use the options supported by that program; these do not automatically update its connection URL.'),
 'working_directory': ('Folder in which the program starts.', r'For example F:\Services\Speech. Leave empty to use the executable folder.', 'Relative files opened by the program may depend on this folder.'),
 'python': ('Python interpreter used to start the dialogue engine.', 'Choose an installed python.exe with the required Mio dependencies, for example MainApp/env/Scripts/python.exe.', 'Changes the engine environment. Close and reopen the interface to change its own interpreter too.'),
 'health_url': ('Address used to check whether this service is ready.', 'Use its full HTTP(S) health or model-list URL, for example http://127.0.0.1:9000/health.', 'Must return the response format expected by Mio. An open port alone is not sufficient.'),
 'snapshot_url': ('Image source used for facial recognition.', 'Use the Agent DVR snapshot URL, for example http://127.0.0.1:8090/liveimage.jpg?oid=1&size=640x480.', 'Selects the camera image sent to face recognition. Changing size affects the requested snapshot, not necessarily the camera capture resolution.'),
 'recognition_url': ('Face-recognition API receiving the camera image.', 'For example http://127.0.0.1:32168/v1/vision/face/recognize.', 'Requires the CodeProject.AI-compatible response used by Mio. Recognition results feed the existing access and mode rules.'),
 'configuration_url': ('Voice changer configuration endpoint.', 'For example http://127.0.0.1:18000/api/configuration-manager/configuration.', 'Mio checks input and output sampling rates here. Changing the URL does not set those rates on the server.'),
 'conversion_url': ('Voice changer audio conversion endpoint.', 'For example http://127.0.0.1:18000/api/voice-changer/convert_chunk.', 'Synthesized speech is sent here for voice conversion; a compatible RVC service is required.'),
 'temperature': ('Randomness of generated replies.', 'Use a decimal accepted by your model, for example 0.6.', 'Higher values usually produce more variation; lower values favor more predictable replies. This does not guarantee accuracy.'),
 'top_p': ('Probability range used to select possible next tokens.', 'For example 0.9; 1.0 leaves this filter unrestricted.', 'Lower values narrow the available choices and can reduce variety.'),
 'repeat_penalty': ('Penalty applied to repeated tokens, when supported by the server.', 'For example 1.05; 1.0 is neutral.', 'Increasing it may reduce repetition but excessive values can distort wording.'),
 'presence_penalty': ('Penalty for tokens already present, when supported.', 'For example 0.0 for neutral behavior.', 'A positive value encourages different wording or topics; support depends on the backend.'),
 'conversation_max_tokens': ('Maximum generated response length.', 'Enter a whole number, for example 300 tokens.', 'A larger budget allows longer replies and more generation time; a small budget may cut a reply short.'),
 'sentence_silence_seconds': ('Silence that ends a spoken phrase.', 'Enter seconds, for example 1.2.', 'Lower values submit sooner but can split a sentence at a hesitation.'),
 'audio_preroll_seconds': ('Audio retained from before detected speech begins.', 'Enter seconds, for example 2.5.', 'A longer buffer helps preserve the beginning of speech but includes more preceding sound.'),
 'memory_quiet_seconds': ('Quiet period before background memory extraction may start.', 'Enter seconds, for example 30.', 'Increasing it delays extraction during a conversation; extraction can compete with the next dialogue request.'),
 'face_poll_seconds': ('Interval between camera recognition requests.', 'Enter seconds, for example 4.', 'A larger interval reduces requests but delays presence updates and interacts with continuous-presence confirmation.'),
 'face_grace_seconds': ('Tolerance for loss of valid face access during conversation.', 'Enter seconds, for example 60.', 'A longer value allows more time for recognition to recover before sleep. Unknown-face confirmation has a separate setting.'),
 'unknown_face_confirm_seconds': ('Continuous unknown-face presence needed before the existing sleep rule applies.', 'Enter seconds, for example 10.', 'A shorter delay reacts sooner to an unknown face; it does not alter voice recognition.'),
 'child_face_confirm_seconds': ('Continuous camera presence needed for Child mode.', 'Enter seconds, for example 10.', 'A longer delay filters brief facial detections. The independent voice-based mode selection is unchanged.'),
 'woman_face_confirm_seconds': ('Camera confirmation delay for Adult mode.', 'Enter seconds, for example 10.', 'A longer delay makes camera-based activation less immediate.'),
 'voice_idle_seconds': ('Conversation inactivity delay.', 'Enter seconds, for example 120.', 'Controls the existing idle-to-sleep timing.'),
 'extraction_batch_size': ('Number of queued sources handled in one memory batch.', 'Enter a whole number, for example 2.', 'Larger batches process the queue faster but may occupy the LLM for longer.'),
 'extraction_batch_spacing_seconds': ('Pause between memory extraction batches.', 'Enter seconds, for example 3.', 'A longer pause reduces how often extraction requests compete with conversation.'),
 'extraction_max_tokens': ('Output token budget for memory extraction.', 'Enter a whole number, for example 900.', 'A small budget may truncate structured extraction output; a large one allows longer processing.'),
 'microphone_name_prefix': ('Beginning of the input device name to select.', 'Copy the matching Windows audio device prefix, for example CABLE Output.', 'Selects the audio source; it does not install or configure a virtual cable.'),
 'microphone_hostapi': ('Windows audio backend used with the selected input.', 'Use an available backend name, for example MME.', 'The device must be available through this backend.'),
 'transparency_percent': ('Chat window transparency.', 'Enter a percentage from 0 to 60; for example 10.', '0 is opaque; higher values reveal more of the desktop. Reopen the interface to apply a form edit; the chat slider applies immediately.'),
 'message_font_size': ('Chat message text size.', 'Enter a positive font size, for example 13.', 'Larger values improve readability and fit less text. Close and reopen the interface to apply.'),
 'message_color': ('Color of chat message text.', 'Enter a Tk color or hex color, for example #86efac.', 'Changes message text color. Close and reopen the interface to apply.'),
 'window_width': ('Initial chat window width.', 'Enter a positive pixel count, for example 780.', 'Changes the next window opening size; close and reopen the interface.'),
 'window_height': ('Initial chat window height.', 'Enter a positive pixel count, for example 390.', 'Changes the next window opening size; close and reopen the interface.'),
 'mainGpu': ('Preferred GPU index for local LM Studio model loading.', 'Use the index exposed by the model runtime, for example 1.', 'Affects the local model loader, not the Windows display order or an external server.'),
 'ratio': ('Fraction of model offloading requested from the local loader.', 'For example 1.0 for full offloading.', 'Higher offloading can require more GPU memory; actual support depends on LM Studio.'),
 'disabledGpus': ('GPU indices excluded by the local model loader.', 'Use a JSON list of numbers, for example [0].', 'These GPUs are excluded from this model load, not disabled system-wide.'),
}

def page_help(path, raw=False):
    path = Path(path)
    if path.name == 'modules.json':
        return ('Choose the base configuration here. Save, then Restart with selected modules; '
                'this restart applies the selected service set. Ordinary prompt/timing edits still use Reload Mio only. '
                'Disabling face recognition removes camera authorization. Speech input groups the microphone, Whisper, Vosk, Silero and WebRTC; '
                'speaker recognition separately identifies voices. The local LLM remains the base dialogue engine. '
                'GPT and Gemini have their own Enabled switches in Services and their dedicated pages.')
    if path.parent.name == 'online':
        return ('Online provider settings: Save, then Reload Mio to apply changes. Wake Mio before selecting GPT or Gemini. '
                'Each provider uses the shared main/family prompt plus its dedicated prompt and separate conversation history. '
                'Keys are stored with the local key buttons, separately from page Save. '
                'Gemini API keys can be created in Google AI Studio. Free-tier models have quotas, and free-tier data may be used to improve Google products; '
                'check model eligibility and current terms in AI Studio. Mio never enables billing or switches to a paid model automatically.')
    if raw:
        return ('Advanced editor: enter valid JSON with double-quoted keys, unchanged value types and required keys. '
                'For field-by-field guidance, turn Advanced JSON editor off. Save stores this page; reload applies service settings.')
    if path.parent.name == 'prompt':
        return ('Purpose: instructions for this conversation mode. Enter plain, natural sentences, for example '
                '"Usually answer in one or two sentences; give details when asked." Effect: guides future replies; '
                'does not guarantee exact wording. Save, then use Reload Mio for main settings; restart an external service separately for its settings. Existing conversation context may still influence replies.')
    if path.name == 'extraction_prompt.txt':
        return ('Purpose: instructions for extracting lasting memories. Preserve the required output format and field names. '
                'Effect: changes future extraction, not memories already stored. Save, then use Reload Mio for main settings; restart an external service separately for its settings.')
    if path.suffix != '.json':
        return ('Purpose: configured text or voice-command phrases for this section. Keep the existing line format; '
                'for example, one spoken command per line. Effect: changes the phrases recognized by this section. '
                'Save, then use Reload Mio for main settings; restart an external service separately for its settings.')
    return ('Save stores this page. Reload to apply changes reloads the Mio engine only. '
            'Window appearance and the interface interpreter require closing and reopening the window.')

def field_help(path, keys, value):
    path = Path(path)
    key = str(keys[-1]) if keys else 'value'
    tip = HELP.get(key)
    if path.parent.name == 'online' and key in ('llm_model', 'tts_model', 'tts_voice'):
        from model_field import model_hint
        hint = model_hint(path.stem, key).replace('\n', ' ')
        tip = (tip[0], hint + ' Copy the exact identifier from your provider account. The example is not selected automatically.', tip[2])
    elif key == 'url':
        destinations = {'llm': ('chat requests', 'http://127.0.0.1:1234/v1/chat/completions'),
                        'transcription': ('audio transcription', 'http://127.0.0.1:9000/v1/audio/transcriptions'),
                        'french_voice': ('French speech synthesis', 'http://127.0.0.1:9881/tts'),
                        'multilingual_voice': ('English/Japanese synthesis', 'http://127.0.0.1:9882/tts'),
                        'memoire_vectorielle': ('memory search and storage', 'http://127.0.0.1:9893')}
        purpose, example = destinations.get(path.stem, ('this service', 'http://127.0.0.1:9000'))
        tip = (f'Address used for {purpose}.', f'Enter the complete address, for example {example}.',
               'Routes requests to that address. The server must already offer the compatible API; this does not change its port or install it.')
    elif key == 'model':
        tip = ('Model identifier used by this component.', 'Copy the exact model identifier from the service configuration.',
               'Selects the requested model. For an external LLM, load it in the server first; changing the name here does not download it.')
    elif key == 'startup_timeout_seconds':
        tip = ('Maximum startup waiting time.', 'Enter seconds; the interface accepts 30 to 1800, for example 900.' if path.name.startswith('interface') else 'Enter seconds, for example 180.',
               'A larger value tolerates slower initialization but delays reporting a startup timeout.')
    elif 'reponse_auto' in path.parts:
        tip = ('Automatic reply content for this event.', 'Keep the existing structure and enter natural phrases; for example "Hello!".',
               'Changes the configured event reply, not ordinary model-generated conversation.')
    elif path.stem == 'conditions_prompt' and isinstance(value, list):
        tip = ('Names, roles or labels matched by the mode selector.', 'Enter one exact recognized name or role per line, matching the recognition configuration.',
               'Changes which recognition results select this mode; it does not enroll faces or voices.')
    if tip:
        return 'Purpose: ' + tip[0] + '\nEnter: ' + tip[1] + '\nEffect: ' + tip[2]
    # Explicit format guidance for advanced fields whose component semantics vary.
    if isinstance(value, bool):
        entry = 'Enable or disable this option.'
    elif isinstance(value, list):
        entry = ('Enter one text item per line.' if all(isinstance(x, str) for x in value)
                 else 'Enter a JSON list, preserving the existing item types, for example [0, 1] for numeric indices.')
    elif isinstance(value, (dict, type(None))):
        entry = 'Use valid JSON and preserve the existing structure; null means no value.'
    elif isinstance(value, (int, float)):
        entry = f'Enter a number without units, for example {value}.'
        if key.endswith('_seconds'):
            entry += ' The unit is seconds.'
        elif key.endswith('_ms'):
            entry += ' The unit is milliseconds.'
        elif key.endswith('_chars'):
            entry += ' The unit is characters.'
    else:
        entry = 'Enter plain text, preserving any placeholders or identifiers already used here.'
    return (f'Advanced setting: {key.replace("_", " ")} ({path.stem}).\n{entry}\n'
            'Effect depends on this component. Keep the current value unless you know its supported meaning and range. Save, then reload service settings.')
