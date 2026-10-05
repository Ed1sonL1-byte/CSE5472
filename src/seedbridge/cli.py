import argparse
from pathlib import Path
import uuid

from .config import ROOT, REACHABILITY_SCENARIOS, RunConfig
from .doctor import inspect_toolchain
from .io import write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="SeedBridge local teaching-fixture integration and evaluation")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="Check the pinned local toolchain")
    doctor.add_argument("--output", type=Path)
    run = commands.add_parser("run", help="Run one complete fixture integration")
    run.add_argument("fixture", choices=list(REACHABILITY_SCENARIOS))
    run.add_argument("--seed", type=int, default=1)
    run.add_argument("--max-prefixes", type=int, default=5)
    run.add_argument("--warmup-tests", type=int, default=400)
    run.add_argument("--process-timeout", type=float, default=60)
    run.add_argument("--total-solve-timeout", type=float, default=180)
    run.add_argument("--output", type=Path, help="New output directory; defaults to runs/<unique-id>")
    report = commands.add_parser("report", help="Render a stored run report")
    report.add_argument("run", type=Path)
    safety_demo = commands.add_parser("safety-demo", help="Confirm the local accounting defect across all tools")
    safety_demo.add_argument("--seed", type=int, default=1)
    safety_demo.add_argument("--warmup-tests", type=int, default=100)
    safety_demo.add_argument("--max-prefixes", type=int, default=5)
    safety_demo.add_argument("--process-timeout", type=float, default=60)
    safety_demo.add_argument("--total-solve-timeout", type=float, default=180)
    safety_demo.add_argument("--output", type=Path, required=True)
    stage2 = commands.add_parser("campaign", help="Run one Stage 2 warmup and comparison arm")
    stage2.add_argument("fixture", choices=list(REACHABILITY_SCENARIOS))
    stage2.add_argument("arm", choices=["native_resume", "concrete_augment", "symbolic_augment"])
    stage2.add_argument("--repeat", type=int, required=True, choices=range(1, 6))
    stage2.add_argument("--config", type=Path, default=ROOT / "configs/stage2-benchmark.json")
    stage2.add_argument("--output", type=Path)
    benchmark = commands.add_parser("benchmark", help="Run the frozen 60-result Stage 2 benchmark")
    benchmark.add_argument("--config", type=Path, default=ROOT / "configs/stage2-benchmark.json")
    benchmark.add_argument("--output", type=Path)
    benchmark_report = commands.add_parser("benchmark-report", help="Rebuild Stage 2 reports offline")
    benchmark_report.add_argument("run", type=Path)
    study_plan = commands.add_parser("study-plan", help="Expand and validate a Stage 3 study matrix")
    study_plan.add_argument("--config", type=Path, default=ROOT / "configs/stage3-study.json")
    study_plan.add_argument("--output", type=Path)
    study = commands.add_parser("study", help="Run a fresh Stage 3 study from a versioned matrix")
    study.add_argument("--config", type=Path, default=ROOT / "configs/stage3-study.json")
    study.add_argument("--output", type=Path)
    study.add_argument("--resume", action="store_true", help="Resume only at a verified common-block boundary")
    study_audit = commands.add_parser("study-audit", help="Independently audit stored Stage 3 raw evidence")
    study_audit.add_argument("study", type=Path)
    study_audit.add_argument("--output", type=Path)
    study_report = commands.add_parser("study-report", help="Rebuild Stage 3 tables and charts offline")
    study_report.add_argument("study", type=Path)
    study_report.add_argument("--output", type=Path)
    study_export = commands.add_parser("study-export", help="Create a self-contained Stage 3 evidence archive")
    study_export.add_argument("study", type=Path)
    study_export.add_argument("--output", type=Path, required=True)
    study_verify = commands.add_parser("study-verify-archive", help="Extract and rebuild a Stage 3 archive twice")
    study_verify.add_argument("archive", type=Path)
    study_verify.add_argument("--output", type=Path, required=True)
    safety_study = commands.add_parser("safety-study", help="Run the frozen 60-slot Stage 4 safety matrix")
    safety_study.add_argument("--config", type=Path, default=ROOT / "configs/stage4-safety-v2.json")
    safety_study.add_argument("--output", type=Path, required=True)
    safety_study.add_argument("--resume", action="store_true")
    safety_audit = commands.add_parser("safety-audit", help="Audit Stage 4 from raw tool records")
    safety_audit.add_argument("study", type=Path)
    safety_audit.add_argument("--output", type=Path)
    safety_report = commands.add_parser("safety-report", help="Render an audited Stage 4 result")
    safety_report.add_argument("study", type=Path)
    safety_report.add_argument("--output", type=Path)
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
        if args.command == "safety-demo":
            from .pipeline import run_pipeline
            config = RunConfig("accounting_flawed", args.seed, args.max_prefixes,
                               args.warmup_tests, args.process_timeout,
                               args.total_solve_timeout)
            result, directory = run_pipeline(config, args.output)
            print(f"{result['status']}: {directory / 'report.md'}")
            return 0 if result["status"] == "safety_confirmed" else 1
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
        if args.command == "study-plan":
            from .study import write_study_plan
            result = write_study_plan(args.config, args.output)
            print(
                f"{result['distinct_slot_count']} distinct slots, "
                f"{result['common_block_count']} common blocks"
            )
            return 0
        if args.command == "study":
            from .study_runner import resume_study, run_study
            if args.resume and args.output is None:
                raise ValueError("--resume requires --output for the existing study")
            directory = (args.output or ROOT / "runs" / f"stage3-{uuid.uuid4().hex[:12]}").resolve()
            result = (resume_study if args.resume else run_study)(args.config, directory)
            expected = result.get("plan", {}).get(
                "distinct_slot_count", result["result_count"])
            print(
                f"{result['evaluation_valid_count']}/{expected} valid: "
                f"{directory / 'manifest.json'}"
            )
            return 0 if result["status"] == "complete" else 1
        if args.command == "study-audit":
            from .study_audit import audit_study
            path = args.study if args.study.exists() else ROOT / "runs" / args.study
            output = args.output or path / "derived/audit.json"
            result = audit_study(path, output)
            print(f"{result['status']}: {result['slot_count']} slots: {output}")
            return 0 if result["status"] == "passed" else 1
        if args.command == "study-report":
            from .study_report import build_study_report
            path = args.study if args.study.exists() else ROOT / "runs" / args.study
            output = args.output or path / "derived"
            result = build_study_report(path, output)
            print(f"{result['audit_status']}: {result['slot_count']} slots: {output / 'summary.md'}")
            return 0 if result["audit_status"] == "passed" else 1
        if args.command == "study-export":
            from .study_export import export_study
            path = args.study if args.study.exists() else ROOT / "runs" / args.study
            result = export_study(path, args.output)
            print(f"created: {result['archive_path']} ({result['archive_sha256']})")
            return 0
        if args.command == "study-verify-archive":
            from .study_export import verify_archive
            result = verify_archive(args.archive, args.output)
            print(f"{result['status']}: {result['extracted_file_count']} archived study files")
            return 0 if result["status"] == "passed" else 1
        if args.command == "safety-study":
            from .study_runner import resume_study, run_study
            directory = args.output.resolve()
            result = (resume_study if args.resume else run_study)(args.config, directory)
            print(f"{result['evaluation_valid_count']}/60 valid: {directory / 'manifest.json'}")
            return 0 if result["status"] == "complete" else 1
        if args.command == "safety-audit":
            from .safety_audit import audit_safety_study, write_safety_report
            path = args.study.resolve()
            output = args.output or path / "derived/audit.json"
            result = audit_safety_study(path, output)
            write_safety_report(result, output.parent)
            print(f"{result['status']}: {result['slot_count']}/60 slots: {output}")
            return 0
        if args.command == "safety-report":
            from .safety_audit import write_safety_report
            from .io import read_json
            path = args.study.resolve()
            audit = read_json(path / "derived/audit.json")
            if audit.get("status") != "passed" or audit.get("slot_count") != 60:
                raise ValueError("Stage 4 independent audit is absent or incomplete")
            output = args.output or path / "derived"
            write_safety_report(audit, output)
            print(output / "summary.md")
            return 0
        from .benchmark import build_benchmark_report
        path = args.run if args.run.exists() else ROOT / "runs" / args.run
        result = build_benchmark_report(path)
        print(path / "summary.md")
        return 0 if result["result_count"] and result["evaluation_valid_count"] == result["result_count"] else 1
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, f"seedbridge: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
