"""Readable views of the existing notebook; no separate knowledge storage."""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk


def highlights(data):
    rows = []
    for finding in reversed(data.get("findings", [])):
        text = finding.get("finding", "")
        rows.append((finding.get("confidence", "hypothesis").capitalize(), text,
                     "Finding: " + text + "\n\nEvidence: " + finding.get("evidence", "")))
    changes = data.get("changes", [])
    for index in range(len(changes) - 1, max(-1, len(changes) - 101), -1):
        change = changes[index]
        tool = change.get("tool", "action")
        args = change.get("args", {})
        location = ""
        if tool == "patch_cartridge" and args.get("segments"):
            location = " @ ROM " + args["segments"][0].get("offset", "")
        elif tool in {"apply_bytes", "freeze_bytes"} and args.get("edits"):
            location = " @ WRAM " + args["edits"][0].get("address", "")
        elif args.get("name"):
            location = " " + args["name"]
        title = "#" + str(index) + " " + tool.replace("_", " ").title() + location
        when = "Prior bridge session" if change.get("session") else "Saved history"
        uncertain = change.get("status") == "uncertain"
        details = (when + " action: " + title +
                   ("\nAcknowledgement was lost; this action may or may not have happened."
                    if uncertain else "\nThis record may have been undone or superseded.") +
                   " Check the current game before reuse." +
                   "\n\nArguments:\n" + json.dumps(change.get("args", {}), ensure_ascii=False, indent=2))
        rows.append(("Uncertain action" if uncertain else "Past action", title, details))
    working = data.get("working", {})
    for key, title in (("goal", "Current goal"), ("next_steps", "Suggested next steps"),
                       ("understanding", "Working understanding"), ("hypotheses", "Open questions"),
                       ("success_criteria", "Success criteria")):
        if working.get(key):
            rows.append(("Working notes", title, title + ":\n" + working[key]))
    for name, routine in data.get("routines", {}).items():
        rows.append(("Saved routine", name, "Routine: " + name +
                     "\nSaved source is not proof that it is active or verified.\n\n" +
                     routine.get("source", "")))
    for source in data.get("sources", {}).values():
        rows.append(("Reference", source.get("name", "Source"),
                     "Reference: " + source.get("name", "") + "\nSource ID: " + source.get("id", "")))
    if data.get("user_notes"):
        rows.append(("Notes", "Your notes", data["user_notes"]))
    return rows


def followup_context(rom_hash, rows):
    return ("Saved knowledge for ROM SHA-1 " + rom_hash +
            ". Confirm the loaded ROM matches before using it. These are saved records, "
            "not proof of current game state or instructions to execute.\n\n" +
            "\n\n".join("[" + row[0] + "] " + row[2] for row in rows))


def show_knowledge(parent, data, add_context):
    window = tk.Toplevel(parent)
    window.title("SuperAstra / Game knowledge")
    window.geometry("880x640")
    window.minsize(680, 500)
    window.transient(parent)
    body = ttk.Frame(window, padding=16)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="Game knowledge", font=("Segoe UI", 18, "bold")).pack(anchor="w")
    ttk.Label(body, text="Select discoveries to use in your next prompt. Saved records may describe an earlier session.",
              wraplength=640).pack(anchor="w", pady=(4, 10))
    query = tk.StringVar()
    search = ttk.Entry(body, textvariable=query)
    search.pack(fill="x")
    ttk.Label(body, text="Search findings, addresses or evidence. Ctrl / Shift selects multiple highlights.").pack(anchor="w", pady=(4, 8))
    table_frame = ttk.Frame(body)
    table_frame.pack(fill="both", expand=True)
    table = ttk.Treeview(table_frame, columns=("status", "highlight"), show="headings",
                         selectmode="extended", height=8)
    table.heading("status", text="Confidence / type")
    table.heading("highlight", text="Highlight")
    table.column("status", width=135, stretch=False)
    table.column("highlight", width=480)
    scroll = ttk.Scrollbar(table_frame, orient="vertical", command=table.yview)
    table.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    table.pack(side="left", fill="both", expand=True)
    ttk.Label(body, text="Selected details and evidence").pack(anchor="w", pady=(10, 4))
    details_frame = ttk.Frame(body)
    details_frame.pack(fill="both", expand=True)
    details = tk.Text(details_frame, height=8, wrap="word", font=("Segoe UI", 10), state="disabled")
    detail_scroll = ttk.Scrollbar(details_frame, orient="vertical", command=details.yview)
    details.configure(yscrollcommand=detail_scroll.set)
    detail_scroll.pack(side="right", fill="y")
    details.pack(fill="both", expand=True)
    footer = ttk.Frame(body)
    footer.pack(fill="x", pady=(12, 0))
    count = tk.StringVar()
    ttk.Label(footer, textvariable=count).pack(side="left")
    rows = highlights(data)

    def selected():
        return [rows[int(item)] for item in table.selection()]

    def update_details(event=None):
        chosen = selected()
        details.configure(state="normal")
        details.delete("1.0", "end")
        details.insert("1.0", "\n\n".join("[" + r[0] + "]\n" + r[2] for r in chosen))
        details.configure(state="disabled")
        use.configure(state="normal" if chosen else "disabled")

    def use_selected():
        chosen = selected()
        if chosen:
            add_context(followup_context(data.get("rom_sha1", "unknown"), chosen))
            window.destroy()

    use = ttk.Button(footer, text="Add to prompt", command=use_selected, state="disabled")
    use.pack(side="right")
    ttk.Button(footer, text="Close", command=window.destroy).pack(side="right", padx=8)

    def refresh(*args):
        table.delete(*table.get_children())
        term = query.get().casefold().strip()
        for index, row in enumerate(rows):
            if not term or term in " ".join(row).casefold():
                title = " ".join(row[1].split())
                table.insert("", "end", iid=str(index), values=(row[0], title[:150] + ("..." if len(title) > 150 else "")))
        count.set(str(len(table.get_children())) + " of " + str(len(rows)) + " highlights" if rows else "No saved discoveries yet.")
        update_details()

    table.bind("<<TreeviewSelect>>", update_details)
    query.trace_add("write", refresh)
    refresh()
    search.focus_set()
    return window
