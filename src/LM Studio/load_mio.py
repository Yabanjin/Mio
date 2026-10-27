"""Load Mio using explicit server-side GPU placement, not CLI environment hints."""
import json
from pathlib import Path
import lmstudio as lms


def main():
    ready = Path(__file__).with_name("mio-gpu-ready.json")
    ready.unlink(missing_ok=True)
    settings = json.loads(Path(__file__).with_name("mio-load.json").read_text(encoding="utf-8-sig"))
    with lms.Client() as client:
        downloaded = client.llm.list_downloaded()
        matches = [m for m in downloaded
                   if settings["model"].casefold() == m.model_key.casefold()]
        if len(matches) != 1:
            raise RuntimeError("Choose an exact model key in mio-load.json: "
                               + repr(settings["model"])
                               + "; available keys: "
                               + repr([m.model_key for m in downloaded]))
        for model in client.llm.list_loaded():
            if model.identifier == settings.get('api_identifier', settings['model']):
                print('Reloading the selected model to apply settings.', flush=True)
                model.unload()
                break
        print('Loading the model with the selected GPU configuration.', flush=True)
        model = client.llm.load_new_instance(matches[0].model_key,
                    instance_identifier=settings.get('api_identifier') or settings['model'], config=settings["config"])
        actual = model.get_load_config().gpu
        requested = settings['config'].get('gpu', {})
        if requested and (actual is None or actual.main_gpu != requested.get('mainGpu')
                          or not set(requested.get('disabledGpus', [])).issubset(actual.disabled_gpus or [])):
            model.unload()
            raise RuntimeError("LM Studio did not confirm the selected GPU assignment.")
        ready.write_text(json.dumps({"gpu": requested.get('mainGpu'), "model": model.identifier}), encoding="utf-8")
        print('Model loaded: ' + model.identifier, flush=True)


if __name__ == "__main__":
    main()
