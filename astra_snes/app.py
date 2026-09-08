from __future__ import annotations

import json
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .agent import AstraAgent, INSTRUCTIONS
from .codex_agent import CodexAgent
from .toolbox import Toolbox
from .transport import Bridge, ROOT

BG, PANEL, FG, MUTED, ACCENT = "#080d24", "#1b2865", "#f4f1ff", "#929bc3", "#f4d38b"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("SUPERASTRA")
        root.geometry("920x920")
        root.minsize(800, 840)
        root.configure(bg=BG)
        self.events = queue.Queue()
        self.busy = False
        self.max_rounds = 32
        self.bridge = Bridge()
        self.toolbox = Toolbox(self.bridge, self.progress)
        self.agent = AstraAgent(self.toolbox, progress=self.progress)
        self.codex = CodexAgent(self.bridge, INSTRUCTIONS, progress=self.progress)
        self.mode = tk.StringVar(value="Codex")
        self.running_mode = None
        self._work_speaker = "Codex"
        self._closing = False
        self.status = tk.StringVar(value="NO CARTRIDGE CONNECTED")
        self.activity = tk.StringVar(value="Ready when you are.")
        from tkinter import font as tkfont
        families = set(tkfont.families(root))
        mono = next((f for f in ("Consolas", "DejaVu Sans Mono", "Courier New") if f in families), "Courier")
        self.menu_font = (mono, 10, "bold")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG, font=(mono, 10))
        style.configure("TButton", background="#293571", foreground=FG, bordercolor="#6575b5",
                        lightcolor="#8291cb", darkcolor="#111a46", borderwidth=2,
                        padding=(14, 10), font=self.menu_font)
        style.map("TButton", background=[("active", "#414f94"), ("pressed", "#202955")],
                  foreground=[("disabled", "#7b83a8")])
        style.configure("Accent.TButton", background=ACCENT, foreground="#251d38",
                        bordercolor="#fff2bf", lightcolor="#fff6d4", darkcolor="#a67b42")
        style.map("Accent.TButton", background=[("active", "#ffe9ad"), ("pressed", "#d3ac65")],
                  foreground=[("disabled", "#766544")])
        style.configure("Menu.TButton", background=PANEL, anchor="w", padding=(10, 10), borderwidth=0)
        style.map("Menu.TButton", background=[("active", "#3d4b96"), ("pressed", "#101b51")])
        style.configure("TRadiobutton", background=BG, foreground=MUTED, font=(mono, 9))
        style.map("TRadiobutton", foreground=[("selected", FG)])
        style.configure("TCheckbutton", background=BG, foreground=FG)
        style.configure("TEntry", fieldbackground=PANEL, foreground=FG, insertcolor=ACCENT, padding=6)
        style.configure("Vertical.TScrollbar", background="#5363a0", troughcolor=PANEL,
                        bordercolor=PANEL, arrowcolor=FG)

        def panel(parent):
            shadow = tk.Frame(parent, bg="#030617", padx=0, pady=0)
            edge = tk.Frame(shadow, bg="#b9c5ef", padx=2, pady=2)
            edge.pack(fill="both", expand=True, padx=(0, 4), pady=(0, 4))
            inset = tk.Frame(edge, bg="#5364a6", padx=2, pady=2)
            inset.pack(fill="both", expand=True)
            inner = tk.Frame(inset, bg=PANEL, padx=16, pady=12)
            inner.pack(fill="both", expand=True)
            return shadow, inner

        outer = tk.Frame(root, bg=BG, padx=24, pady=16)
        outer.pack(fill="both", expand=True)
        header = tk.Canvas(outer, height=138, bg=BG, highlightthickness=0)
        header.pack(fill="x")
        # Header pixels are deliberately static: no distracting idle animation on video.
        for x, y, size, color in [(14, 30, 3, "#7884cb"), (562, 31, 3, "#9a85d1"),
                                  (577, 91, 2, "#5666a0"), (20, 113, 2, "#5666a0")]:
            header.create_rectangle(x, y, x + size, y + size, fill=color, outline="")
        try:
            self.logo_original = tk.PhotoImage(file=str(ROOT / "assets" / "superastra-logo.png"), format="png")
            self.logo = self.logo_original.subsample(4, 4)
            header.create_image(286, 66, image=self.logo)
        except (tk.TclError, OSError):
            header.create_text(24, 65, anchor="w", text="SUPERASTRA", fill=FG, font=(mono, 35, "bold"))
        header.create_text(286, 122, text="Change the game.", fill=MUTED, font=(mono, 10))
        credit = tk.Frame(header, bg=BG)
        credit.place(relx=1.0, x=-4, y=20, anchor="ne")
        try:
            self.spellbook_logo = tk.PhotoImage(file=str(ROOT / "assets" / "spellbook-logo.png"), format="png")
            tk.Label(credit, text="Magic by", bg=BG, fg=MUTED, font=(mono, 10)).pack(anchor="e", pady=(0, 5))
            tk.Label(credit, image=self.spellbook_logo, bg=BG, borderwidth=0).pack(anchor="e")
        except (tk.TclError, OSError):
            tk.Label(credit, text="Magic by Spellbook", bg=BG, fg=FG, font=(mono, 10)).pack(anchor="e")
        settings = ttk.Button(header, text="SETTINGS", command=self.settings)
        settings.place(relx=1.0, x=-4, y=92, anchor="ne")

        status_frame, status_inner = panel(outer)
        status_frame.pack(fill="x", pady=(0, 12))
        status_inner.configure(pady=8)
        tk.Label(status_inner, text="CARTRIDGE", bg=PANEL, fg="#b3a0e5", font=(mono, 9, "bold")).pack(side="left", padx=(0, 16))
        self.status_label = tk.Label(status_inner, textvariable=self.status, bg=PANEL, fg=FG,
                                    font=(mono, 10), anchor="w", justify="left", wraplength=640)
        self.status_label.pack(side="left", fill="x", expand=True)

        modes = ttk.Frame(outer)
        modes.pack(fill="x", pady=(0, 10))
        self.backend_buttons = []
        for label, value in (("CODEX / CHATGPT", "Codex"), ("OPENAI API", "Astra"), ("LOCAL SHORTCUTS", "Local")):
            button = ttk.Radiobutton(modes, text=label, variable=self.mode, value=value)
            button.pack(side="left", padx=(0, 16))
            self.backend_buttons.append(button)
        ttk.Label(modes, text="CTRL + ENTER TO CAST", foreground=MUTED, font=(mono, 9)).pack(side="right", padx=(0, 4))

        prompt_frame, prompt_inner = panel(outer)
        prompt_frame.pack(fill="x")
        prompt_title = tk.Frame(prompt_inner, bg=PANEL)
        prompt_title.pack(fill="x", pady=(0, 8))
        tk.Label(prompt_title, text="YOUR COMMAND", bg=PANEL, fg=ACCENT, font=(mono, 11, "bold")).pack(side="left")
        tk.Label(prompt_title, text="WRITE A LITTLE MAGIC", bg=PANEL, fg="#aab5ed", font=(mono, 9)).pack(side="right")
        self.prompt = tk.Text(prompt_inner, height=3, bg=PANEL, fg=FG, insertbackground=ACCENT,
                              insertwidth=3, relief="flat", borderwidth=0, highlightthickness=0,
                              padx=0, pady=6, font=(mono, 18), wrap="word",
                              selectbackground="#6658a5", selectforeground="#ffffff")
        self.prompt.pack(fill="x")
        self.prompt.insert("1.0", "Drop a star")
        self.prompt.bind("<Control-Return>", lambda event: (self.send(), "break")[1])
        arrow = tk.Canvas(prompt_inner, height=9, bg=PANEL, highlightthickness=0)
        arrow.pack(fill="x")
        arrow.bind("<Configure>", lambda e: (arrow.delete("all"), arrow.create_polygon(
            e.width - 16, 0, e.width - 2, 0, e.width - 9, 7, fill=FG, outline="")))

        row = ttk.Frame(outer)
        row.pack(fill="x", pady=(12, 16))
        self.send_button = ttk.Button(row, text="CAST PROMPT", style="Accent.TButton", command=self.send)
        self.send_button.pack(side="left")
        ttk.Button(row, text="STOP THINKING", command=self.cancel).pack(side="left", padx=10)
        for title, prompt in [("DROP A STAR", "Drop a star"), ("5 CHUCKS", "Put 5 chucks on the screen")]:
            ttk.Button(row, text=title, command=lambda p=prompt: self.fill(p)).pack(side="right", padx=(8, 4))

        lower = tk.Frame(outer, bg=BG)
        lower.pack(fill="both", expand=True)
        menu_frame, menu_inner = panel(lower)
        menu_frame.pack(side="right", fill="y", padx=(14, 0))
        menu_inner.configure(padx=8)
        tk.Label(menu_inner, text="MENU", bg=PANEL, fg=ACCENT, font=(mono, 11, "bold")).pack(anchor="w", padx=10, pady=(0, 8))
        for title, action in [("> UNDO", lambda: self.action("undo", {})),
                              ("> STOP EFFECTS", lambda: self.action("stop_cheats", {"name": ""})),
                              ("> RESUME", self.resume),
                              ("> CLEAR PROMPT", lambda: self.fill("")),
                              ("> GAME KNOWLEDGE", self.view_knowledge),
                              ("> ADD CONTEXT", self.import_context)]:
            ttk.Button(menu_inner, text=title, style="Menu.TButton", command=action).pack(fill="x", pady=1)
        log_frame, log_inner = panel(lower)
        log_frame.pack(side="left", fill="both", expand=True)
        tk.Label(log_inner, text="SESSION LOG", bg=PANEL, fg="#b3a0e5", font=(mono, 10, "bold")).pack(anchor="w", pady=(0, 10))
        text_row = tk.Frame(log_inner, bg=PANEL)
        text_row.pack(fill="both", expand=True)
        self.transcript = tk.Text(text_row, height=7, bg=PANEL, fg=FG, relief="flat", borderwidth=0,
                                  highlightthickness=0, padx=0, pady=3, font=(mono, 11),
                                  spacing1=3, spacing3=5, wrap="word", state="disabled")
        scroll = ttk.Scrollbar(text_row, orient="vertical", command=self.transcript.yview)
        scroll.pack(side="right", fill="y", padx=(8, 0))
        self.transcript.configure(yscrollcommand=scroll.set)
        self.transcript.pack(side="left", fill="both", expand=True)
        self.transcript.tag_configure("you", foreground=ACCENT, font=(mono, 10, "bold"))
        self.transcript.tag_configure("detail", foreground="#c6b3fc", font=(mono, 10, "bold"))
        self.log("SuperAstra", "What would you like to change? Codex mode uses ChatGPT sign-in in Settings.")
        self.footer = ttk.Label(outer, textvariable=self.activity, foreground=MUTED,
                               font=(mono, 9), wraplength=850)
        self.footer.pack(anchor="w", pady=(10, 0))
        root.bind("<Configure>", self.resize_labels, add="+")
        root.after(100, self.drain)
        root.after(500, self.poll)
        root.protocol("WM_DELETE_WINDOW", self.close)

    def resize_labels(self, event):
        if event.widget == self.root:
            self.status_label.configure(wraplength=max(420, event.width - 215))
            self.footer.configure(wraplength=max(500, event.width - 65))

    def progress(self, message: str):
        self.events.put(("progress", message))

    def log(self, speaker: str, text: str):
        self.transcript.configure(state="normal")
        self.transcript.insert("end", speaker.upper() + "\n", "you" if speaker == "You" else "detail")
        self.transcript.insert("end", text + "\n\n")
        self.transcript.see("end")
        self.transcript.configure(state="disabled")

    def fill(self, prompt: str):
        self.prompt.delete("1.0", "end")
        self.prompt.insert("1.0", prompt)
        self.prompt.focus_set()

    def work(self, fn, backend=None):
        if self.busy or self._closing:
            return
        self.busy = True
        self.running_mode = backend or self.mode.get()
        self._work_speaker = {"Codex": "Codex", "Astra": "Astra / API", "Local": "Local command"}[self.running_mode]
        self.send_button.configure(state="disabled")
        for button in self.backend_buttons:
            button.configure(state="disabled")
        def run():
            try:
                result = fn()
                self.events.put(("answer", result if isinstance(result, str) else json.dumps(result, indent=2)))
            except Exception as e:
                self.events.put(("error", str(e)))
            finally:
                self.events.put(("done", ""))
        threading.Thread(target=run, daemon=True).start()

    def send(self):
        if self.busy:
            return
        prompt = self.prompt.get("1.0", "end").strip()
        if not prompt:
            return
        self.log("You", prompt)
        mode = self.mode.get()
        self.agent.cancel.clear()
        self.codex.cancel.clear()
        if mode == "Codex":
            self.work(lambda: self.codex.run(prompt, max_rounds=self.max_rounds))
        elif mode == "Astra":
            self.work(lambda: self.agent.run(prompt, max_rounds=self.max_rounds))
        else:
            self.work(lambda: self.toolbox.local(prompt))

    def resume(self):
        if self.busy:
            return
        if self.mode.get() == "Local":
            self.activity.set("Select Codex / ChatGPT or OpenAI API before resuming an investigation.")
            return
        self.fill("Continue")
        self.send()

    def view_knowledge(self):
        if self.busy:
            return
        def read():
            self.agent.cancel.clear()
            self.toolbox.begin()
            return self.toolbox.notebook.summary()
        self.work(read)

    def action(self, name: str, args: dict):
        if self.busy:
            self.activity.set("Stop the current task and wait for it to finish, then retry Undo / Stop Effects.")
            return
        self.agent.cancel.clear()
        self.work(lambda: (self.toolbox.begin(), self.toolbox.dispatch(name, args))[1], backend="Local")

    def cancel(self):
        if self.running_mode == "Codex":
            self.codex.cancel.set()
            self.activity.set("Stopping Codex. Waiting for the current emulator operation to settle; changes are not undone.")
        else:
            self.agent.cancel.set()
            self.activity.set("Stopping before the next tool. Current API request may still be in flight.")

    def drain(self):
        while True:
            try:
                kind, message = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                self.activity.set(message)
                if message.startswith(("Codex →", "Astra →", "Spawned", "Executed", "Applied", "Tool result:")):
                    self.log("Activity", message)
            elif kind == "answer":
                self.log(self._work_speaker, message)
            elif kind == "error":
                self.log("Could not complete", message)
                self.activity.set("Check the session message above.")
            elif kind == "done":
                self.busy = False
                self.running_mode = None
                self.send_button.configure(state="normal")
                for button in self.backend_buttons:
                    button.configure(state="normal")
        self.root.after(100, self.drain)

    def poll(self):
        try:
            state = self.bridge.heartbeat()
            self.status.set("Connected: " + state["title"] + f"   |   Undo: {state['undo_count']}   |   Effects: {state['hold_count'] + len(state.get('routines', []))}")
            if state.get("last_routine_error"):
                self.activity.set("An effect stopped: " + state["last_routine_error"])
        except Exception:
            self.status.set("NO CARTRIDGE CONNECTED")
        self.root.after(1000, self.poll)

    def settings(self):
        if self.busy or self._closing:
            self.activity.set("Wait for the current task to finish before changing settings.")
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("SUPERASTRA / Settings")
        dialog.configure(bg=BG)
        dialog.transient(self.root)
        tabs = ttk.Notebook(dialog)
        tabs.pack(fill="both", expand=True, padx=18, pady=18)
        codex_frame, api_frame = ttk.Frame(tabs, padding=18), ttk.Frame(tabs, padding=18)
        tabs.add(codex_frame, text="Codex / ChatGPT")
        tabs.add(api_frame, text="OpenAI API (separate billing)")

        def entry(parent, label, value, hidden=False):
            ttk.Label(parent, text=label).pack(anchor="w")
            widget = ttk.Entry(parent, width=62, show="*" if hidden else "")
            widget.insert(0, str(value))
            widget.pack(fill="x", pady=(4, 12))
            return widget

        cli = entry(codex_frame, "Codex executable (blank = find installed Codex; no command-line flags)", self.codex.executable)
        codex_model = entry(codex_frame, "Codex model", self.codex.model)
        minutes = entry(codex_frame, "Maximum minutes per Codex request (1-120)", int(self.codex.timeout / 60))
        ttk.Label(codex_frame, text="Type in this window; Codex CLI runs in the background.\n"
                  "Sign-in uses a separate SuperAstra Codex profile, even if your regular Codex is logged in.\n"
                  "No API-key fallback. Shell execution, apps, hooks and web search are disabled.\n"
                  "Prompts, selected game data and screenshots still go to OpenAI through Codex.\n"
                  "Codex keeps its own credentials and conversation history in the profile below:",
                  foreground=MUTED, wraplength=520, justify="left").pack(anchor="w", pady=(0, 8))
        ttk.Label(codex_frame, text=str(self.codex.home), foreground=MUTED, wraplength=520).pack(anchor="w")

        key = entry(api_frame, "OpenAI API key (held in this app's memory only)", self.agent.api_key, hidden=True)
        model = entry(api_frame, "API model", self.agent.model)
        search = tk.BooleanVar(value=self.agent.web_search)
        ttk.Checkbutton(api_frame, text="Let the API backend research game documentation on the web", variable=search).pack(anchor="w")
        ttk.Label(api_frame, text="API mode is billed separately to your OpenAI project.\n"
                  "It is never automatically selected when Codex fails or reaches a usage limit.",
                  foreground=MUTED, wraplength=520).pack(anchor="w", pady=12)
        footer = ttk.Frame(dialog, padding=(18, 0, 18, 18))
        footer.pack(fill="x")
        steps = entry(footer, "Request budget: Codex MCP calls / API rounds (1-256)", self.max_rounds)

        def apply_values():
            if self.busy or self._closing:
                return False
            try:
                budget, duration = int(steps.get()), int(minutes.get())
                if not 1 <= budget <= 256 or not 1 <= duration <= 120:
                    raise ValueError()
            except ValueError:
                messagebox.showerror("Request limits", "Use 1-256 steps and 1-120 minutes.", parent=dialog)
                return False
            self.max_rounds = budget
            self.codex.executable = cli.get().strip()
            self.codex.model = codex_model.get().strip() or "gpt-6-astra"
            self.codex.timeout = duration * 60
            self.agent.api_key = key.get().strip()
            self.agent.model = model.get().strip() or "gpt-6-astra"
            self.agent.web_search = search.get()
            return True

        def codex_action(operation):
            if apply_values():
                self.codex.cancel.clear()
                dialog.destroy()
                self.work(operation, backend="Codex")

        actions = ttk.Frame(codex_frame)
        actions.pack(fill="x", pady=(16, 0))
        ttk.Button(actions, text="Sign in with ChatGPT", command=lambda: codex_action(self.codex.login)).pack(side="left")
        ttk.Button(actions, text="Check sign-in", command=lambda: codex_action(self.codex.check_login)).pack(side="left", padx=8)
        ttk.Button(codex_frame, text="New Codex conversations", command=lambda: codex_action(self.codex.reset_threads)).pack(anchor="w", pady=(8, 0))

        def apply():
            if apply_values():
                dialog.destroy()
        ttk.Button(footer, text="Apply settings", command=apply, style="Accent.TButton").pack(anchor="e")

    def import_context(self):
        if self.busy:
            return
        paths = filedialog.askopenfilenames(title="Add source files and memory maps for this ROM", filetypes=[("Text and source", "*.txt *.md *.asm *.inc *.sym *.map *.json *.c *.h"), ("All files", "*")])
        if not paths:
            return
        def load():
            from pathlib import Path
            self.agent.cancel.clear()
            self.toolbox.begin()
            messages = []
            for path in paths:
                try:
                    messages.append(self.toolbox.notebook.import_source(Path(path))["message"])
                except (OSError, ValueError) as e:
                    messages.append("Could not import " + Path(path).name + ": " + str(e))
            return "\n".join(messages)
        self.work(load)

    def close(self):
        if self._closing:
            return
        self._closing = True
        self.cancel()
        self._wait_for_close()

    def _wait_for_close(self):
        if self.busy:
            self.root.after(100, self._wait_for_close)
        else:
            self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()
