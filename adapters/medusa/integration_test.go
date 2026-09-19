package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"
)

func readReport(t *testing.T, path string) runReport {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var report runReport
	if err := json.Unmarshal(data, &report); err != nil {
		t.Fatal(err)
	}
	return report
}

func TestNativeRestartObserverAndDeterminism(t *testing.T) {
	if os.Getenv("SEEDBRIDGE_INTEGRATION") != "1" {
		t.Skip("set SEEDBRIDGE_INTEGRATION=1 with pinned Forge/crytic-compile environment")
	}
	for _, id := range []string{"phase_counter", "bounded_ledger", "range_gate", "workflow_gate"} {
		t.Run(id, func(t *testing.T) {
			fx := testFixture(t, id)
			dir := t.TempDir()
			opts := runOptions{Output: filepath.Join(dir, "warmup", "observed.json"), CorpusDir: filepath.Join(dir, "warmup", "corpus"), Seed: 1, Tests: 30, MaxSteps: 3, Timeout: 30 * time.Second, Observe: true}
			if err := runObserved(fx, opts); err != nil {
				t.Fatal(err)
			}
			warmup := readReport(t, opts.Output)
			var prefix *sequenceRecord
			for _, s := range warmup.Sequences {
				last := s.Steps[len(s.Steps)-1]
				if last.Observe[0] == "2" && last.Observe[3] == false {
					prefix = s
					break
				}
			}
			if prefix == nil {
				t.Fatal("native warmup did not produce a usable prefix")
			}
			seq, err := readSequence(prefix.NativePath, fx)
			if err != nil {
				t.Fatal(err)
			}
			var restarts []runReport
			for _, enabled := range []bool{true, false} {
				name := "off"
				if enabled {
					name = "on"
				}
				corpusDir := filepath.Join(dir, name, "corpus")
				if _, err := writeSequence(filepath.Join(corpusDir, "call_sequences", "input.json"), seq); err != nil {
					t.Fatal(err)
				}
				opts := runOptions{Output: filepath.Join(dir, name, "observed.json"), CorpusDir: corpusDir, Seed: 1, Tests: 1, MaxSteps: 3, Timeout: 30 * time.Second, Observe: enabled}
				if err := runObserved(fx, opts); err != nil {
					t.Fatal(err)
				}
				report := readReport(t, opts.Output)
				last := report.Sequences[len(report.Sequences)-1]
				if !last.Replayed || !last.Admitted || !last.Complete {
					t.Fatal("restart missing actual completion/admission evidence")
				}
				if last.AdmissionEvidence["kind"] != "medusa_v1.5.1_post_sequence_event" {
					t.Fatal("unexpected admission evidence")
				}
				if enabled && !reflect.DeepEqual(last.Steps[len(last.Steps)-1].Observe, prefix.Steps[len(prefix.Steps)-1].Observe) {
					t.Fatal("restart changed observed state")
				}
				restarts = append(restarts, report)
			}
			on, off := restarts[0], restarts[1]
			if on.CoverageBranches == 0 || on.CoverageDigest != off.CoverageDigest || on.CoverageBranches != off.CoverageBranches {
				t.Fatal("observer changed native coverage")
			}
			onSeq, offSeq := on.Sequences[len(on.Sequences)-1], off.Sequences[len(off.Sequences)-1]
			for i, a := range onSeq.Steps {
				b := offSeq.Steps[i]
				if a.Calldata != b.Calldata || a.Status != b.Status || a.GasUsed != b.GasUsed || a.BlockNumber != b.BlockNumber || a.BlockTimestamp != b.BlockTimestamp || a.StateRootAfterObserver != b.StateRootAfterObserver || a.CoverageDigest != b.CoverageDigest || !a.ObserverStateUnchanged {
					t.Fatalf("observer changed execution at step %d", i)
				}
			}
			opts.Output = filepath.Join(dir, "repeat", "observed.json")
			opts.CorpusDir = filepath.Join(dir, "repeat", "corpus")
			if err := runObserved(fx, opts); err != nil {
				t.Fatal(err)
			}
			repeat := readReport(t, opts.Output)
			if len(warmup.Sequences) != len(repeat.Sequences) {
				t.Fatal("same-seed sequence count differs")
			}
			for i, seq := range warmup.Sequences {
				if seq.NativeDigest != repeat.Sequences[i].NativeDigest || !reflect.DeepEqual(seq.Steps, repeat.Sequences[i].Steps) {
					t.Fatalf("same-seed warmup differs at prefix %d", i)
				}
			}
			t.Logf("%s: 30 native sequences repeated exactly; prefix %d steps; restart on/off roots, receipts, coverage digest, and admission agree", id, len(prefix.Steps))
		})
	}
}
