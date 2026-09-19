import argparse
from pathlib import Path

from .config import ROOT, SCENARIOS, RunConfig
from .doctor import inspect_toolchain
from .io import write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 1 integration for two local teaching fixtures")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="Check the pinned local toolchain")
    doctor.add_argument("--output", type=Path)
    run = commands.add_parser("run", help="Run one complete fixture integration")
    run.add_argument("fixture", choices=list(SCENARIOS))
    run.add_argument("--seed", type=int, default=1)
    run.add_argument("--max-prefixes", type=int, default=5)
    run.add_argument("--warmup-tests", type=int, default=400)
    run.add_argument("--process-timeout", type=float, default=60)
    run.add_argument("--total-solve-timeout", type=float, default=180)
    run.add_argument("--output", type=Path, help="New output directory; defaults to runs/<unique-id>")
    report = commands.add_parser("report", help="Render a stored run report")
    report.add_argument("run", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "doctor":
            result = inspect_toolchain()
            if args.output:
                write_json(args.output, result)
            for name, check in result["tools"].items():
                print(f"{'OK' if check['ok'] else 'FAIL'} {name}: {check.get('path') or 'not installed'}")
            print(f"{'OK' if result['python']['ok'] else 'FAIL'} Python: {result['python']['version']}")
            return 0 if result["ok"] else 1
        if args.command == "run":
            from .pipeline import run_pipeline
            config = RunConfig(args.fixture, args.seed, args.max_prefixes, args.warmup_tests,
                               args.process_timeout, args.total_solve_timeout)
            result, directory = run_pipeline(config, args.output)
            print(f"{result['status']}: {directory / 'report.md'}")
            return 0 if result["status"] == "stage1_confirmed" else 1
        from .report import regenerate
        path = args.run if args.run.exists() else ROOT / "runs" / args.run
        print(regenerate(path))
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, f"seedbridge: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
