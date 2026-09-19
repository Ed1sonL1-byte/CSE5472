package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

const adapterVersion = "0.2.0"
const medusaVersion = "v1.5.1"

func main() {
	if err := runCLI(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "medusa-adapter:", err)
		os.Exit(1)
	}
}

func runCLI(args []string) error {
	if len(args) == 0 {
		return errors.New("expected version, run-observed, run-campaign, decode-corpus, roundtrip, encode-candidate, or encode-batch")
	}
	if args[0] == "version" {
		return json.NewEncoder(os.Stdout).Encode(map[string]string{"adapter_version": adapterVersion, "medusa_version": medusaVersion})
	}
	fs := flag.NewFlagSet(args[0], flag.ContinueOnError)
	fixtureID := fs.String("fixture", "", "one of the four repository teaching fixtures")
	input := fs.String("input", "", "native sequence file")
	output := fs.String("output", "", "new output JSON file")
	argument := fs.String("argument", "", "decimal uint256 suffix argument")
	prefixLength := fs.Int("prefix-length", 0, "optional positive prefix length for codec commands")
	corpusDir := fs.String("corpus-dir", "", "local corpus directory")
	lineageOutput := fs.String("lineage-output", "", "new JSONL lineage output for run-campaign")
	seed := fs.Int64("seed", 1, "single worker RNG seed")
	tests := fs.Int("tests", 100, "number of complete sequences; stop only at the completion event")
	maxSteps := fs.Int("max-steps", 3, "new sequence length, 1 to 4")
	timeout := fs.Duration("timeout", 30*time.Second, "fuzzing wall-clock limit after compilation")
	observe := fs.Bool("observe", true, "read fixture state after every call")
	recordLineage := fs.Bool("record-lineage", true, "record patched native parent selection lineage")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	if fs.NArg() != 0 {
		return errors.New("unexpected positional arguments")
	}
	if *output == "" {
		return errors.New("--output is required")
	}
	outputPath, err := filepath.Abs(*output)
	if err != nil {
		return err
	}
	if _, err := os.Stat(outputPath); err == nil {
		return fmt.Errorf("output already exists: %s", outputPath)
	}
	fx, err := loadFixture(*fixtureID)
	if err != nil {
		return err
	}
	switch args[0] {
	case "run-observed":
		if *corpusDir == "" || *tests < 1 || *tests > 10000 || *maxSteps < 1 || *maxSteps > 4 || *timeout <= 0 || *timeout > 5*time.Minute {
			return errors.New("run requires --corpus-dir, 1..10000 tests, 1..4 max-steps, and timeout in (0,5m]")
		}
		corpusPath, err := filepath.Abs(*corpusDir)
		if err != nil {
			return err
		}
		return runObserved(fx, runOptions{Output: outputPath, CorpusDir: corpusPath, Seed: *seed, Tests: *tests, MaxSteps: *maxSteps, Timeout: *timeout, Observe: *observe})
	case "run-campaign":
		if *corpusDir == "" || *tests < 2 || *tests > 10000 || *maxSteps != 4 || *timeout <= 0 || *timeout > 5*time.Minute {
			return errors.New("campaign requires --corpus-dir, 2..10000 tests, --max-steps 4, and timeout in (0,5m]")
		}
		corpusPath, err := filepath.Abs(*corpusDir)
		if err != nil {
			return err
		}
		lineagePath := *lineageOutput
		if lineagePath != "" {
			lineagePath, err = filepath.Abs(lineagePath)
			if err != nil {
				return err
			}
			if _, err := os.Stat(lineagePath); err == nil {
				return fmt.Errorf("lineage output already exists: %s", lineagePath)
			}
		}
		return runObserved(fx, runOptions{Output: outputPath, CorpusDir: corpusPath, LineageOutput: lineagePath, Seed: *seed, Tests: *tests, MaxSteps: *maxSteps, Timeout: *timeout, Observe: *observe, Campaign: true, RecordLineage: *recordLineage})
	case "roundtrip", "decode-corpus", "encode-candidate":
		if *input == "" {
			return errors.New("--input is required")
		}
		seq, err := readSequence(*input, fx)
		if err != nil {
			return err
		}
		if *prefixLength != 0 {
			if *prefixLength < 1 || *prefixLength > len(seq) {
				return errors.New("prefix-length is outside input sequence")
			}
			seq = seq[:*prefixLength]
		}
		if args[0] == "encode-candidate" {
			seq, err = appendCandidate(seq, fx, *argument)
			if err != nil {
				return err
			}
		}
		if args[0] == "decode-corpus" {
			return writeJSON(outputPath, sequenceSummary(seq))
		}
		_, err = writeSequence(outputPath, seq)
		return err
	case "encode-batch":
		if *input == "" {
			return errors.New("--input batch plan is required")
		}
		return encodeCandidateBatch(*input, outputPath, fx)
	default:
		return fmt.Errorf("unknown command %q", args[0])
	}
}

func writeJSON(path string, value any) error {
	b, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return err
	}
	return os.WriteFile(path, append(b, '\n'), 0644)
}
