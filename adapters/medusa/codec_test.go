package main

import (
	"encoding/json"
	"math/big"
	"os"
	"path/filepath"
	"testing"

	"github.com/crytic/medusa/fuzzing/calls"
)

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
	name := "begin"
	if fx.ID == "bounded_ledger" {
		name = "open"
	}
	method := fx.ABI.Methods[name]
	msg := calls.NewCallMessageWithAbiValueData(actor, &targetAddress, 0, big.NewInt(0), 12500000, big.NewInt(1), big.NewInt(0), big.NewInt(0), &calls.CallMessageDataAbiValues{Method: &method, InputValues: []any{}})
	return calls.CallSequence{calls.NewCallSequenceElement(nil, msg, 0, 0)}
}

func TestNativeCodecPreservesMaximumUint256(t *testing.T) {
	for _, id := range []string{"phase_counter", "bounded_ledger"} {
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

func TestRejectInvalidCandidateParameters(t *testing.T) {
	fx := testFixture(t, "phase_counter")
	tooLarge := new(big.Int).Lsh(big.NewInt(1), 256).String()
	for _, arg := range []string{"", "-1", "+1", "1.0", "0x10", tooLarge} {
		if _, err := appendCandidate(oneNativeCall(t, fx), fx, arg); err == nil {
			t.Fatalf("accepted %q", arg)
		}
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
