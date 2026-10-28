"""Open the interface without services and validate its settings pages."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'interface'))
from app import MioApp
from settings_pages import SECTIONS
from settings_store import catalog, read

app = MioApp()
try:
    app.root.update()
    app.root.update_idletasks()
    assert app.process is None and app.manager is None
    for section in SECTIONS:
        entries = catalog(section)
        for label, path in entries:
            read(path)
        print(f'OK {section}: {len(entries)} settings entries', flush=True)
    app.customize()
    app.editor.withdraw()
    app.root.update_idletasks()
    assert app.draft.winfo_height() > 20
    print('OK interface, editor, fixed input panel and no service startup', flush=True)
finally:
    app.root.destroy()
