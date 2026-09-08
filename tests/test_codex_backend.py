"""Codex backend regression tests. No real model calls or credentials are used."""
from pathlib import Path
import json
import os
import subprocess
import sys
import threading
import time
import uuid

import pytest

from astra_snes import codex_agent as backend
from astra_snes.codex_agent import CodexAgent, CodexError, clean_environment, identity

THREAD = "0199a213-81c0-7800-8aa1-bbab2a035a53"
CONTEXT = {"session": "session-one", "romhash": "a" * 40, "epoch": 1}


class Bridge:
    def __init__(self):
        self.context = dict(CONTEXT)
        self.calls = []

    def rpc(self, op):
        self.calls.append(op)
        assert op == "inspect"
        return dict(self.context)


@pytest.fixture
def agent(tmp_path, monkeypatch):
    script = tmp_path / "fake codex.py"
    script.write_text('''
import json, os, sys, time
from pathlib import Path
home = Path(os.environ["CODEX_HOME"])
if "login" in sys.argv:
    if (home / "login-fail").exists():
        print("private-secret-never-display", file=sys.stderr)
        sys.exit(1)
    print("Logged in using ChatGPT", file=sys.stderr)
    sys.exit(0)
data = json.loads(sys.stdin.buffer.read())
(home / "capture.json").write_text(json.dumps({"args": sys.argv[2:], "payload": data, "env": dict(os.environ)}))
def emit(value):
    print(json.dumps(value), flush=True)
emit({"type": "thread.started", "thread_id": "0199a213-81c0-7800-8aa1-bbab2a035a53"})
request = data["user_request"]
if request == "invalid-json":
    print("not-json", flush=True)
    time.sleep(60)
if request == "host-operation":
    emit({"type": "item.started", "item": {"type": "command_execution", "command": "NOT EXECUTED"}})
    time.sleep(60)
if request == "wrong-server":
    emit({"type": "item.started", "item": {"type": "mcp_tool_call", "server": "other", "tool": "write"}})
    time.sleep(60)
emit({"type": "item.started", "item": {"type": "mcp_tool_call", "server": "superastra", "tool": "get_context"}})
if request in ("sleep", "timeout"):
    (home / "sleeping").write_text(str(os.getpid()))
    time.sleep(60)
if request == "fail":
    emit({"type": "turn.failed", "error": {"message": "private-secret-never-display"}})
    sys.exit(1)
if request == "error-event":
    emit({"type": "error", "message": "private-secret-never-display"})
emit({"type": "item.completed", "item": {"type": "agent_message", "text": "Fake answer: " + request}})
if request != "no-completion":
    emit({"type": "turn.completed", "usage": {"input_tokens": 1}})
if request == "nonzero":
    sys.exit(2)
''', encoding="utf-8")
    monkeypatch.setattr(backend, "executable_command", lambda *a, **k: [sys.executable, str(script)])
    monkeypatch.setattr(backend, "STOP_GRACE", 0.15)
    messages = []
    instance = CodexAgent(Bridge(), "Trusted SNES investigation instructions", messages.append,
                          root=tmp_path / "repo with spaces", state_directory=tmp_path / "private")
    instance.messages = messages
    return instance


def capture(agent):
    return json.loads((agent.home / "capture.json").read_text())


def test_clean_environment_is_allowlist():
    env = clean_environment(Path("/private"), {
        "PATH": "/bin", "SystemRoot": r"C:\Windows", "OPENAI_API_KEY": "fake-key",
        "CODEX_API_KEY": "fake-key", "CODEX_ACCESS_TOKEN": "fake-token",
        "OPENAI_BASE_URL": "https://invalid.test", "NODE_OPTIONS": "--require bad",
        "PYTHONPATH": "/untrusted", "MY_PASSWORD": "fake-password", "CODEX_HOME": "/other",
    })
    assert env["CODEX_HOME"] == "/private"
    assert env["SystemRoot"] == r"C:\Windows"
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "OPENAI_BASE_URL",
                "NODE_OPTIONS", "PYTHONPATH", "MY_PASSWORD"):
        assert key not in env


@pytest.mark.parametrize("bad", [{}, {**CONTEXT, "epoch": True}, {**CONTEXT, "epoch": -1},
                                  {**CONTEXT, "session": ""}, {**CONTEXT, "romhash": None}])
def test_identity_validation(bad):
    with pytest.raises(CodexError):
        identity(bad)


@pytest.mark.parametrize("thread", [None, THREAD])
def test_security_flags_preserved_on_start_and_resume(agent, thread):
    argv = agent.command(CONTEXT, Path("/cancel"), Path("/instructions"), 32, thread)
    options = dict(argv[i + 1].split("=", 1) for i, a in enumerate(argv) if a == "-c")
    assert options["forced_login_method"] == '"chatgpt"'
    assert options["approval_policy"] == '"never"'
    assert options["sandbox_mode"] == '"read-only"'
    for key in ("shell_tool", "unified_exec", "apps", "hooks", "multi_agent"):
        assert options["features." + key] == "false"
    assert options["mcp_servers.superastra.required"] == "true"
    assert "--ignore-user-config" in argv and "--strict-config" in argv
    assert not any(x in argv for x in ("--last", "--yolo", "--full-auto", "--dangerously-bypass-approvals-and-sandbox"))
    assert argv[-1] == "-"
    if thread:
        assert argv[-3:] == ["resume", thread, "-"]
    mcp = json.loads(options["mcp_servers.superastra.args"])
    assert json.loads(mcp[mcp.index("--expected-context") + 1]) == CONTEXT
    assert mcp[mcp.index("--max-tools") + 1] == "32"


@pytest.mark.parametrize("budget", [0, 257, True, "32"])
def test_invalid_budget(agent, budget):
    with pytest.raises(CodexError):
        agent.command(CONTEXT, Path("/cancel"), Path("/instructions"), budget)


@pytest.mark.parametrize("model", ["--yolo", "model\nflag", "gpt; touch x"])
def test_model_cannot_supply_flags(agent, model):
    agent.model = model
    with pytest.raises(CodexError):
        agent.command(CONTEXT, Path("/cancel"), Path("/instructions"), 32)


def test_user_prompt_is_only_stdin_not_argv(agent, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-must-not-leak")
    prompt = '--yolo " && echo hacked; $(whoami) %APPDATA%\nMake Mario fly 😎'
    assert agent.run(prompt) == "Fake answer: " + prompt
    data = capture(agent)
    assert data["payload"]["user_request"] == prompt
    assert prompt not in data["args"]
    assert "OPENAI_API_KEY" not in data["env"]
    assert data["env"]["CODEX_HOME"] == str(agent.home)
    assert agent.bridge.calls == ["inspect"]
    assert any("Codex → get_context" in x for x in agent.messages)
    assert list(agent.directory.glob("cancel-*.flag"))
    assert not list(agent.directory.glob("instructions-*.md"))


def test_resume_is_explicit_and_per_rom_and_model(agent):
    agent.run("first")
    assert "resume" not in capture(agent)["args"]
    agent.run("second")
    assert capture(agent)["args"][-3:] == ["resume", THREAD, "-"]
    agent.bridge.context["romhash"] = "b" * 40
    agent.run("other game")
    assert "resume" not in capture(agent)["args"]
    agent.model = "different-model"
    agent.run("other model")
    assert "resume" not in capture(agent)["args"]


def test_resume_survives_agent_restart(agent):
    agent.run("first")
    other = CodexAgent(agent.bridge, "instructions", root=agent.root, state_directory=agent.directory)
    other.run("second")
    assert capture(agent)["args"][-3:] == ["resume", THREAD, "-"]


def test_reset_threads_does_not_delete_credentials(agent):
    agent.prepare()
    auth = agent.home / "auth.json"
    auth.write_text("FAKE test data, not credentials")
    agent.run("first")
    agent.reset_threads()
    assert auth.read_text() == "FAKE test data, not credentials"
    agent.run("second")
    assert "resume" not in capture(agent)["args"]


def test_cancel_before_start_does_not_launch(agent):
    agent.cancel.set()
    with pytest.raises(CodexError, match="Stopped before"):
        agent.run("do not launch")
    assert not agent.directory.exists()


def test_login_failure_never_sends_prompt_or_falls_back(agent):
    agent.prepare()
    (agent.home / "login-fail").touch()
    with pytest.raises(CodexError) as caught:
        agent.run("must not run")
    assert "private-secret" not in str(caught.value)
    assert agent.bridge.calls == []
    assert not (agent.home / "capture.json").exists()


def test_successful_login_and_status(agent):
    assert "Signed into Codex with ChatGPT" in agent.login()
    assert "will not fall back" in agent.check_login()
    assert not agent.bridge.calls


@pytest.mark.parametrize("prompt", ["nonzero", "no-completion", "error-event", "host-operation", "wrong-server"])
def test_incomplete_or_unsafe_runs_not_reported_as_success(agent, prompt):
    with pytest.raises(CodexError) as caught:
        agent.run(prompt)
    assert "private-secret" not in str(caught.value)
    assert list(agent.directory.glob("cancel-*.flag"))


@pytest.mark.parametrize("prompt", ["invalid-json", "fail", "timeout"])
def test_failed_and_timed_out_turns_explicitly_stopped(agent, prompt):
    if prompt == "timeout":
        agent.timeout = 0.15
    text = agent.run(prompt)
    assert "Stopped." in text
    assert "Fake answer" not in text
    assert "private-secret" not in text


def test_stop_kills_only_child_and_keeps_cancellation_marker(agent):
    result = []
    worker = threading.Thread(target=lambda: result.append(agent.run("sleep")))
    worker.start()
    deadline = time.monotonic() + 5
    while not (agent.home / "sleeping").exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert (agent.home / "sleeping").exists()
    agent.cancel.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert "Stopped." in result[0] and "not an Undo" in result[0]
    assert list(agent.directory.glob("cancel-*.flag"))


def test_parallel_request_rejected(agent):
    agent._run_lock.acquire()
    try:
        with pytest.raises(CodexError, match="already running"):
            agent.run("second")
    finally:
        agent._run_lock.release()


def test_corrupt_thread_index_fails_closed_and_can_be_reset(agent):
    agent.prepare()
    (agent.directory / "threads.json").write_text('{"a": "--last"}')
    with pytest.raises(CodexError, match="thread index"):
        agent.run("should not run")
    agent.reset_threads()
    assert "Fake answer" in agent.run("new")


def test_subprocess_never_uses_shell(agent, monkeypatch):
    real_popen = subprocess.Popen
    calls = []
    def checking(argv, **kwargs):
        calls.append(kwargs)
        assert isinstance(argv, list)
        assert kwargs["shell"] is False
        assert kwargs["cwd"] == agent.workspace
        return real_popen(argv, **kwargs)
    monkeypatch.setattr(backend.subprocess, "Popen", checking)
    agent.run("hello")
    assert len(calls) >= 2

@pytest.mark.parametrize("machine,package,target", [
    ("AMD64", "codex-win32-x64", "x86_64-pc-windows-msvc"),
    ("ARM64", "codex-win32-arm64", "aarch64-pc-windows-msvc"),
])
def test_windows_npm_native_resolution_without_batch_or_node(tmp_path, machine, package, target):
    shim = tmp_path / "npm with spaces" / "codex.cmd"
    binary = shim.parent / "node_modules" / "@openai" / package / "vendor" / target / "bin" / "codex.exe"
    binary.parent.mkdir(parents=True)
    binary.touch()
    assert backend.windows_npm_binary(shim, machine) == binary.resolve()


def test_unrecognized_windows_install_fails_closed(tmp_path):
    with pytest.raises(CodexError):
        backend.windows_npm_binary(tmp_path / "codex.cmd", "AMD64")


def test_windows_spawn_hides_console_and_uses_new_process_group(agent, monkeypatch):
    monkeypatch.setattr(backend, "IS_WINDOWS", True)
    monkeypatch.setattr(backend.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(backend.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)
    capture = {}
    monkeypatch.setattr(backend.subprocess, "Popen", lambda args, **kw: capture.update(args=args, **kw))
    agent._spawn([r"C:\Program Files\Codex\codex.exe", "exec"])
    assert capture["creationflags"] == 0x08000200
    assert capture["shell"] is False


def test_cancellation_marker_write_failure_still_kills_child(agent, monkeypatch):
    real_write = backend.private_write
    def failing_marker(path, text):
        if path.suffix == ".flag":
            raise PermissionError("synthetic cancellation-file failure")
        return real_write(path, text)
    monkeypatch.setattr(backend, "private_write", failing_marker)
    killed = []
    real_kill = agent._kill_tree
    def recording_kill(process):
        killed.append(process.pid)
        return real_kill(process)
    monkeypatch.setattr(agent, "_kill_tree", recording_kill)
    with pytest.raises(PermissionError):
        agent.run("normal response")
    assert killed


def test_unicode_paths_remain_valid_toml(agent):
    import tomllib
    instructions = Path("/profile/Ashton 🚀/instructions.md")
    cancel = Path("/profile/Ashton 🚀/cancel.flag")
    argv = agent.command(CONTEXT, cancel, instructions, 32)
    config = tomllib.loads("\n".join(argv[i + 1] for i, value in enumerate(argv) if value == "-c"))
    assert config["model_instructions_file"] == str(instructions)
    assert str(cancel) in config["mcp_servers"]["superastra"]["args"]
