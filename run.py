#!/usr/bin/env python3
"""Start the desktop app, or send a command from a terminal."""
import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(description="Astra-powered SNES emulator companion")
    parser.add_argument("--prompt", help="Send one prompt from the terminal")
    parser.add_argument("--local", action="store_true", help="Use explicitly offline Mario shortcuts")
    parser.add_argument("--status", action="store_true", help="Read live bridge status")
    parser.add_argument("--model", help="OpenAI model ID (default: gpt-6-astra)")
    parser.add_argument("--no-web", action="store_true", help="Disable Astra web research")
    parser.add_argument("--steps", type=int, default=32, help="Investigation steps per request, 1–256 (default 32); progress is saved")
    parser.add_argument("--doctor", action="store_true", help="Check local prerequisites without contacting OpenAI")
    args = parser.parse_args()
    if args.doctor:
        from astra_snes.transport import Bridge, ROOT
        print("Python:", sys.version.split()[0])
        try:
            import tkinter
            print("Tkinter: available")
        except ImportError:
            print("Tkinter: unavailable; use the CLI or install your OS's Python Tk package")
        print("Lua script:", ROOT / "LOAD-IN-BIZHAWK.lua")
        bridge = Bridge()
        try:
            print("Emulator:", bridge.heartbeat()["title"])
        except RuntimeError as e:
            print("Emulator:", e)
        return
    if args.prompt or args.status:
        from astra_snes.agent import AstraAgent
        from astra_snes.toolbox import Toolbox
        from astra_snes.transport import Bridge
        progress = lambda message: print(message, file=sys.stderr, flush=True)
        toolbox = Toolbox(Bridge(), progress)
        if args.status:
            result = toolbox.begin()
        elif args.local:
            result = toolbox.local(args.prompt)
        else:
            result = AstraAgent(toolbox, model=args.model, web_search=not args.no_web, progress=progress).run(args.prompt, max_rounds=args.steps)
        print(result if isinstance(result, str) else json.dumps(result, indent=2))
    else:
        from astra_snes.app import main as gui
        gui()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError, ImportError) as e:
        print("Astra SNES:", str(e), file=sys.stderr)
        sys.exit(1)
