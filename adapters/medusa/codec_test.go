package main

import (
	"encoding/json"
	"errors"
	"math/big"
	"os"
	"path/filepath"
	"testing"

	"github.com/crytic/medusa/fuzzing/calls"
)

func TestRunErrorTakesPrecedenceOverTimeout(t *testing.T) {
	status, detail := classifyRunOutcome(errors.New("worker failed"), true)
	if status != "tool_error" || detail != "worker failed" {
		t.Fatalf("simultaneous error and timeout classified as %q (%q)", status, detail)
	}
	status, detail = classifyRunOutcome(nil, true)
	if status != "timeout" || detail != "" {
		t.Fatalf("plain timeout classified as %q (%q)", status, detail)
	}
	status, detail = classifyRunOutcome(nil, false)
	if status != "complete" || detail != "" {
		t.Fatalf("successful run classified as %q (%q)", status, detail)
	}
}

func testFixture(t *testing.T, id string) *fixture {
	t.Helper()
	fx, err := loadFixture(id)
	if err != nil {
		t.Fatal(err)
	}
	return fx
}

func oneNativeCall(t *testing.T, fx *fixture) calls.CallSequence {
	t.Helper()
	name := map[string]string{
		"phase_counter": "begin", "bounded_ledger": "open",
		"range_gate": "begin", "workflow_gate": "start",
	}[fx.ID]
	method := fx.ABI.Methods[name]
	msg := calls.NewCallMessageWithAbiValueData(actor, &targetAddress, 0, big.NewInt(0), 12500000, big.NewInt(1), big.NewInt(0), big.NewInt(0), &calls.CallMessageDataAbiValues{Method: &method, InputValues: []any{}})
	return calls.CallSequence{calls.NewCallSequenceElement(nil, msg, 0, 0)}
}

func TestNativeCodecPreservesMaximumUint256(t *testing.T) {
	for _, id := range []string{"phase_counter", "bounded_ledger", "range_gate", "workflow_gate"} {
		t.Run(id, func(t *testing.T) {
			fx := testFixture(t, id)
			max := new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), 256), big.NewInt(1))
			seq, err := appendCandidate(oneNativeCall(t, fx), fx, max.String())
			if err != nil {
				t.Fatal(err)
			}
			path := filepath.Join(t.TempDir(), "native.json")
			sha, err := writeSequence(path, seq)
			if err != nil {
				t.Fatal(err)
			}
			data, _ := os.ReadFile(path)
			if sha != sha256Hex(data) {
				t.Fatal("digest is not original file SHA256")
			}
			decoded, err := readSequence(path, fx)
			if err != nil {
				t.Fatal(err)
			}
			last := decoded[len(decoded)-1]
			if last.Call.DataAbiValues.InputValues[0].(*big.Int).Cmp(max) != 0 {
				t.Fatal("uint256 precision lost")
			}
			out := filepath.Join(t.TempDir(), "roundtrip.json")
			sha2, err := writeSequence(out, decoded)
			if err != nil {
				t.Fatal(err)
			}
			if sha != sha2 {
				t.Fatal("native codec changed valid sequence")
			}
		})
	}
}

func TestEncodeCandidateBatchUsesNativeCodecForEveryEntry(t *testing.T) {
	fx := testFixture(t, "phase_counter")
	dir := t.TempDir()
	input := filepath.Join(dir, "input.json")
	if _, err := writeSequence(input, oneNativeCall(t, fx)); err != nil {
		t.Fatal(err)
	}
	first := filepath.Join(dir, "first.json")
	second := filepath.Join(dir, "second.json")
	requests := []batchCandidateRequest{
		{Input: input, Output: first, Argument: "0"},
		{Input: input, Output: second, Argument: "17"},
	}
	plan := filepath.Join(dir, "plan.json")
	data, err := json.Marshal(requests)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(plan, data, 0644); err != nil {
		t.Fatal(err)
	}
	result := filepath.Join(dir, "result.json")
	if err := encodeCandidateBatch(plan, result, fx); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{first, second} {
		sequence, err := readSequence(path, fx)
		if err != nil {
			t.Fatal(err)
		}
		if len(sequence) != 2 || sequence[1].Call.Nonce != 1 {
			t.Fatal("batch output did not append one native candidate call")
		}
	}
	var report struct {
		Fixture string           `json:"fixture"`
		Entries []map[string]any `json:"entries"`
	}
	reportData, err := os.ReadFile(result)
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(reportData, &report); err != nil {
		t.Fatal(err)
	}
	if report.Fixture != fx.ID || len(report.Entries) != len(requests) {
		t.Fatal("batch result omitted an encoded candidate")
	}
}

func TestRejectInvalidCandidateParameters(t *testing.T) {
	fx := testFixture(t, "phase_counter")
	tooLarge := new(big.Int).Lsh(big.NewInt(1), 256).String()
	for _, arg := range []string{"", "-1", "+1", "1.0", "0x10", tooLarge} {
		if _, err := appendCandidate(oneNativeCall(t, fx), fx, arg); err == nil {
			t.Fatalf("accepted %q", arg)
		}
	}
}

func TestSequenceIdentityTracksCallsButIgnoresNonceAndTiming(t *testing.T) {
	fx := testFixture(t, "phase_counter")
	base := oneNativeCall(t, fx)
	first, err := nativeSequenceIdentity(base)
	if err != nil {
		t.Fatal(err)
	}
	changedContext, err := base.Clone()
	if err != nil {
		t.Fatal(err)
	}
	changedContext[0].Call.Nonce = 99
	changedContext[0].BlockNumberDelay = 7
	changedContext[0].BlockTimestampDelay = 11
	second, err := nativeSequenceIdentity(changedContext)
	if err != nil {
		t.Fatal(err)
	}
	if first != second {
		t.Fatal("nonce or timing changed canonical sequence identity")
	}
	changedCall, err := appendCandidate(base, fx, "17")
	if err != nil {
		t.Fatal(err)
	}
	third, err := nativeSequenceIdentity(changedCall)
	if err != nil {
		t.Fatal(err)
	}
	if first == third {
		t.Fatal("calldata or call structure did not change canonical sequence identity")
	}
}

func TestRejectMetadataMismatchAndUnsupportedContext(t *testing.T) {
	fx := testFixture(t, "phase_counter")
	tests := map[string]func(calls.CallSequence){
		"calldata":   func(seq calls.CallSequence) { seq[0].Call.Data = append(seq[0].Call.Data, 0) },
		"sender":     func(seq calls.CallSequence) { seq[0].Call.From = deployer },
		"value":      func(seq calls.CallSequence) { seq[0].Call.Value = big.NewInt(1) },
		"nonce":      func(seq calls.CallSequence) { seq[0].Call.Nonce = 4 },
		"delay":      func(seq calls.CallSequence) { seq[0].BlockTimestampDelay = 1 },
		"skipchecks": func(seq calls.CallSequence) { seq[0].Call.SkipNonceChecks = true },
	}
	for name, mutate := range tests {
		t.Run(name, func(t *testing.T) {
			seq := oneNativeCall(t, fx)
			mutate(seq)
			path := filepath.Join(t.TempDir(), "bad.json")
			data, err := json.Marshal(seq)
			if err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(path, data, 0644); err != nil {
				t.Fatal(err)
			}
			if _, err := readSequence(path, fx); err == nil {
				t.Fatal("unsupported native input accepted")
			}
		})
	}
}
