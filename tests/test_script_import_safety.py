import importlib.util
import socket
from pathlib import Path

import sounddevice
import soundfile


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = _PROJECT_ROOT / "scripts"


def test_importing_manual_scripts_has_no_external_side_effects(monkeypatch):
    def reject_network(*args, **kwargs):
        raise AssertionError("Script import attempted a network connection")

    def reject_recording(*args, **kwargs):
        raise AssertionError("Script import attempted to record audio")

    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_network)
    monkeypatch.setattr(sounddevice, "rec", reject_recording)
    monkeypatch.setattr(sounddevice, "play", reject_recording)
    monkeypatch.setattr(soundfile, "write", reject_recording)

    for script_path in sorted(_SCRIPTS_DIR.glob("*.py")):
        module_name = f"manual_script_import_{script_path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, script_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
