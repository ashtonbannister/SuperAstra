"""Real Tk widgets with fake backends; no Codex login, API call or emulator."""
import importlib.util
from pathlib import Path
import sys
import threading
import time
import types

import pytest

tk = pytest.importorskip("tkinter")
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def ui(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; run under Xvfb or on a desktop")
    calls = []

    class FakeAgent:
        def __init__(self, toolbox, progress):
            self.cancel = threading.Event()
            self.api_key, self.model, self.web_search = "", "gpt-6-astra", True
        def run(self, prompt, max_rounds):
            calls.append(("API", prompt, max_rounds))
            return "API result"

    class FakeToolbox:
        def __init__(self, bridge, progress):
            self.notebook = types.SimpleNamespace(summary=lambda: {"notes": []})
        def begin(self):
            pass
        def local(self, prompt):
            calls.append(("Local", prompt))
            return "Local result"
        def dispatch(self, name, args):
            calls.append(("Direct", name))
            return {"message": "Direct result"}

    class FakeBridge:
        def heartbeat(self):
            raise RuntimeError("No emulator in this UI test")

    for name, values in {
        "astra_snes.agent": {"AstraAgent": FakeAgent, "INSTRUCTIONS": "test instructions"},
        "astra_snes.toolbox": {"Toolbox": FakeToolbox},
        "astra_snes.transport": {"Bridge": FakeBridge, "ROOT": ROOT},
    }.items():
        module = types.ModuleType(name)
        module.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("astra_snes._ui_under_test", ROOT / "astra_snes" / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = module.App(root)
    def codex_run(prompt, max_rounds):
        calls.append(("Codex", prompt, max_rounds))
        return "Codex result"
    app.codex.run = codex_run
    root.update()
    yield app, calls
    try:
        root.destroy()
    except tk.TclError:
        pass


def settle(app):
    deadline = time.monotonic() + 3
    while app.busy and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.01)
    assert not app.busy


def test_selector_defaults_to_codex(ui):
    app, calls = ui
    assert app.mode.get() == "Codex"
    assert [button.cget("value") for button in app.backend_buttons] == ["Codex", "Astra", "Local"]
    assert calls == []


@pytest.mark.parametrize("mode,expected", [("Codex", "Codex"), ("Astra", "API"), ("Local", "Local")])
def test_cast_prompt_routes_to_selected_backend(ui, mode, expected):
    app, calls = ui
    app.mode.set(mode)
    app.fill("Make Mario fly")
    app.send()
    settle(app)
    assert calls[0][0:2] == (expected, "Make Mario fly")
    assert len(calls) == 1


def test_codex_error_never_falls_back_to_api(ui):
    app, calls = ui
    def fail(*args, **kwargs):
        raise RuntimeError("Fake Codex failure")
    app.codex.run = fail
    app.send()
    settle(app)
    assert calls == []
    assert "Fake Codex failure" in app.transcript.get("1.0", "end")


def test_busy_blocks_selector_and_direct_mutations(ui):
    app, calls = ui
    released = threading.Event()
    app.codex.run = lambda *a, **k: (released.wait(2), "Finished")[1]
    app.send()
    assert all(str(button.cget("state")) == "disabled" for button in app.backend_buttons)
    app.action("undo", {})
    app.send()
    assert calls == []
    released.set()
    settle(app)
    assert all(str(button.cget("state")) == "normal" for button in app.backend_buttons)


def test_stop_routes_to_running_backend(ui):
    app, calls = ui
    app.codex.run = lambda *a, **k: (app.codex.cancel.wait(2), "Stopped")[1]
    app.send()
    app.cancel()
    assert app.codex.cancel.is_set()
    assert not app.agent.cancel.is_set()
    settle(app)


def test_resume_does_not_switch_to_api(ui):
    app, calls = ui
    app.resume()
    settle(app)
    assert app.mode.get() == "Codex"
    assert calls[0][0:2] == ("Codex", "Continue")


def test_resume_local_does_not_launch_an_ai_backend(ui):
    app, calls = ui
    app.mode.set("Local")
    app.resume()
    assert calls == [] and not app.busy


def test_reply_label_uses_running_backend_not_later_selection(ui):
    app, calls = ui
    app.send()
    app.mode.set("Astra")  # Programmatic change simulates a stale UI state.
    settle(app)
    text = app.transcript.get("1.0", "end")
    assert "CODEX\nCodex result" in text
    assert "ASTRA / API\nCodex result" not in text


def test_settings_opens_separate_backend_tabs(ui):
    app, calls = ui
    app.settings()
    app.root.update()
    from tkinter import ttk
    def widgets(parent):
        for child in parent.winfo_children():
            yield child
            yield from widgets(child)
    notebooks = [w for w in widgets(app.root) if isinstance(w, ttk.Notebook)]
    assert len(notebooks) == 1
    labels = [notebooks[0].tab(tab, "text") for tab in notebooks[0].tabs()]
    assert labels == ["Codex / ChatGPT", "OpenAI API (separate billing)"]
    assert calls == []
