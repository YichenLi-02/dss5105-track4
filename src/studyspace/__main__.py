"""Command line: `studyspace serve` (default) runs the local web server; `studyspace synth` rewrites the
synthetic data files in data/synthetic/."""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="studyspace", description="Studyspace student productivity agent")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="run the local server (default)")
    serve.add_argument("--host", default="127.0.0.1", help="127.0.0.1 keeps it on this computer")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true", help="restart when code changes")
    synth = sub.add_parser("synth", help="write the synthetic dataset to data/synthetic/")
    synth.add_argument("--out", default=None, help="output folder (default: data/synthetic)")
    args = parser.parse_args(argv)

    if args.command == "synth":
        from .config import load_settings
        from .synthetic import write

        print(f"wrote {write(args.out or load_settings().synthetic_dir)}")
        return

    import uvicorn

    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 8000)
    print(f"Studyspace running at http://{host}:{port}  (API docs: http://{host}:{port}/docs)")
    uvicorn.run("studyspace.api.app:create_app", factory=True, host=host, port=port, reload=getattr(args, "reload", False))


if __name__ == "__main__":
    main()
