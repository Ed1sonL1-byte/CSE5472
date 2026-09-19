import argparse
from pathlib import Path
import uuid

from .config import ROOT, SCENARIOS, RunConfig
from .doctor import inspect_toolchain
from .io import write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="SeedBridge local teaching-fixture integration and evaluation")
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
    stage2 = commands.add_parser("campaign", help="Run one Stage 2 warmup and comparison arm")
    stage2.add_argument("fixture", choices=list(SCENARIOS))
    stage2.add_argument("arm", choices=["native_resume", "concrete_augment", "symbolic_augment"])
    stage2.add_argument("--repeat", type=int, required=True, choices=range(1, 6))
    stage2.add_argument("--config", type=Path, default=ROOT / "configs/stage2-benchmark.json")
    stage2.add_argument("--output", type=Path)
    benchmark = commands.add_parser("benchmark", help="Run the frozen 60-result Stage 2 benchmark")
    benchmark.add_argument("--config", type=Path, default=ROOT / "configs/stage2-benchmark.json")
    benchmark.add_argument("--output", type=Path)
    benchmark_report = commands.add_parser("benchmark-report", help="Rebuild Stage 2 reports offline")
    benchmark_report.add_argument("run", type=Path)
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
        if args.command == "report":
            from .report import regenerate
            path = args.run if args.run.exists() else ROOT / "runs" / args.run
            print(regenerate(path))
            return 0
        if args.command == "campaign":
            from .benchmark import run_single
            directory = (args.output or ROOT / "runs" /
                         f"campaign-{args.fixture}-{args.arm}-{args.repeat}").resolve()
            result = run_single(args.config, args.fixture, args.arm, args.repeat, directory)
            print(f"{'valid' if result['evaluation_valid'] else 'invalid'}: {directory / 'arm/campaign.json'}")
            return 0 if result["evaluation_valid"] else 1
        if args.command == "benchmark":
            from .benchmark import run_benchmark
            directory = (args.output or ROOT / "runs" / f"stage2-{uuid.uuid4().hex[:12]}").resolve()
            result = run_benchmark(args.config, directory)
            print(f"{result['evaluation_valid_count']}/{result['result_count']} valid: {directory / 'summary.md'}")
            return 0 if result["result_count"] == 60 and result["evaluation_valid_count"] == 60 else 1
        from .benchmark import build_benchmark_report
        path = args.run if args.run.exists() else ROOT / "runs" / args.run
        result = build_benchmark_report(path)
        print(path / "summary.md")
        return 0 if result["result_count"] and result["evaluation_valid_count"] == result["result_count"] else 1
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, f"seedbridge: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
