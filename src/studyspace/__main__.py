"""Command line: `studyspace serve` (default) runs the local web server; `studyspace synth` rewrites the
synthetic data files in data/synthetic/; `studyspace evaluate` scores extraction and planning."""

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
    ev = sub.add_parser("evaluate", help="score extraction against labels and the planner against reference cases")
    ev.add_argument("--sources", default=None, help="folder of .eml files or a CSV (default: data/synthetic/emails)")
    ev.add_argument("--gold", default=None, help="gold.json, or member 3's .xlsx label workbook (default: data/synthetic/gold.json)")
    ev.add_argument("--out", default=None, help="write the Markdown report here")
    args = parser.parse_args(argv)

    if args.command == "evaluate":
        _evaluate(args)
        return

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


def _evaluate(args) -> None:
    from pathlib import Path

    from .academic_calendar import AcademicCalendar
    from .config import PROJECT_ROOT, load_settings
    from .evaluation import evaluate_extraction, evaluate_planner, load_gold_json, load_member3_xlsx, markdown_report
    from .extraction import extract
    from .ingest import parse_csv, parse_eml

    settings = load_settings()
    src_path = Path(args.sources) if args.sources else settings.synthetic_dir / "emails"
    gold_path = Path(args.gold) if args.gold else settings.synthetic_dir / "gold.json"
    if src_path.is_dir():
        sources = [s for f in sorted(src_path.glob("*.eml")) for s in parse_eml(f.read_bytes(), f.name).sources]
    else:
        sources = parse_csv(src_path.read_bytes()).sources
    if gold_path.suffix == ".xlsx":
        gold, non_task = load_member3_xlsx(gold_path), {}
    else:
        gold, non_task = load_gold_json(gold_path)
    candidates = extract(sources, AcademicCalendar.load(settings.calendar_path))
    report = markdown_report(
        f"Evaluation: {src_path.name} against {gold_path.name}",
        evaluate_extraction(candidates, gold, non_task),
        evaluate_planner(PROJECT_ROOT / "tests" / "fixtures" / "reference_cases.json"),
    )
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(report)


if __name__ == "__main__":
    main()
