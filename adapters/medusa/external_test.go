package main

import (
	"encoding/json"
	"math/big"
	"os"
	"path/filepath"
	"testing"
)

func TestExternalReplayReadsPublicCountWithoutChangingBytecode(t *testing.T) {
	cases := []struct {
		id       string
		steps    []externalStep
		expected []*big.Int
		holds    []bool
	}{
		{"sb_multitx_onefunc", []externalStep{{"run(uint256)", "2"}, {"run(uint256)", "2"}},
			[]*big.Int{big.NewInt(1), maxUint256()}, []bool{true, false}},
		{"sb_multitx_onefunc", []externalStep{{"run(uint256)", "1"}, {"run(uint256)", "1"}},
			[]*big.Int{big.NewInt(1), big.NewInt(0)}, []bool{true, true}},
		{"sb_multitx_multifunc", []externalStep{{"init()", ""}, {"run(uint256)", "2"}},
			[]*big.Int{big.NewInt(1), maxUint256()}, []bool{true, false}},
		{"sb_multitx_multifunc", []externalStep{{"run(uint256)", "2"}},
			[]*big.Int{big.NewInt(1)}, []bool{true}},
		{"sb_overflow_benign", []externalStep{{"run(uint256)", "2"}},
			[]*big.Int{big.NewInt(1)}, []bool{true}},
	}
	for _, item := range cases {
		name := item.id
		for _, step := range item.steps {
			name += "/" + step.Signature + ":" + step.Argument
		}
		t.Run(name, func(t *testing.T) {
			fx, err := loadExternalFixture(item.id)
			if err != nil {
				t.Fatal(err)
			}
			if fx.RevertedExpected != "none" || !fx.External || fx.Getter != "count" {
				t.Fatalf("external metadata = %+v", fx)
			}
			spec := externalTargets[item.id]
			if sha256Hex(fx.Init) != spec.InitSHA256 || sha256Hex(fx.Runtime) != spec.RuntimeSHA256 {
				t.Fatal("compiled bytecode differs from the pinned hash")
			}
			dir := t.TempDir()
			input := filepath.Join(dir, "calls.json")
			output := filepath.Join(dir, "replay.json")
			encoded, err := json.Marshal(externalReplayRequest{Steps: item.steps})
			if err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(input, encoded, 0644); err != nil {
				t.Fatal(err)
			}
			if err := replayExternal(fx, input, output); err != nil {
				t.Fatal(err)
			}
			var report struct {
				Mode                string `json:"mode"`
				RepairedCounterpart string `json:"repaired_counterpart"`
				FuzzerPrefix        bool   `json:"fuzzer_prefix"`
				Steps               []stepRecord
			}
			data, err := os.ReadFile(output)
			if err != nil {
				t.Fatal(err)
			}
			if err := json.Unmarshal(data, &report); err != nil {
				t.Fatal(err)
			}
			if report.Mode != "external_direct_replay" || report.RepairedCounterpart != "none" || report.FuzzerPrefix {
				t.Fatalf("unexpected report metadata: %+v", report)
			}
			if len(report.Steps) != len(item.expected) {
				t.Fatalf("step count %d", len(report.Steps))
			}
			for index, step := range report.Steps {
				if !step.Success || !step.ObserverStateUnchanged || step.StateRootBeforeObserver != step.StateRootAfterObserver {
					t.Fatalf("step %d changed state or reverted: %+v", index, step)
				}
				if step.Observe[0] != item.expected[index].String() || step.PropertyHolds == nil || *step.PropertyHolds != item.holds[index] {
					t.Fatalf("step %d count/property = %v / %v", index, step.Observe, step.PropertyHolds)
				}
				if step.From != actor.Hex() || step.To != targetAddress.Hex() || step.Value != "0" {
					t.Fatalf("step %d actor/value changed", index)
				}
			}
		})
	}
}

func TestExternalScenarioRejectsOwnedFixtureAndUnknownCall(t *testing.T) {
	if _, err := loadExternalFixture("phase_counter"); err == nil {
		t.Fatal("owned fixture accepted as an external scenario")
	}
	fx, err := loadExternalFixture("sb_overflow_benign")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := externalCalldata(fx, "init()", nil); err == nil {
		t.Fatal("benign target accepted init()")
	}
}

func maxUint256() *big.Int {
	return new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), 256), big.NewInt(1))
}
