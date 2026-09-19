package main

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math/big"
	"os"
	"path/filepath"

	"github.com/crytic/medusa/fuzzing/calls"
)

func readSequence(path string, fx *fixture) (calls.CallSequence, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	if len(b) > 1<<20 {
		return nil, fmt.Errorf("native sequence exceeds 1 MiB")
	}
	var seq calls.CallSequence
	if err := json.Unmarshal(b, &seq); err != nil {
		return nil, fmt.Errorf("native CallSequence decode: %w", err)
	}
	if len(seq) < 1 || len(seq) > 4 {
		return nil, fmt.Errorf("native sequence must have 1..4 calls")
	}
	for i, element := range seq {
		if element == nil || element.Call == nil {
			return nil, fmt.Errorf("nil call at step %d", i)
		}
		msg := element.Call
		if msg.From != actor || msg.To == nil || *msg.To != targetAddress {
			return nil, fmt.Errorf("step %d does not use the fixed fixture actor/deployment", i)
		}
		if msg.Value == nil || msg.Value.Sign() != 0 || msg.GasPrice == nil || msg.GasFeeCap == nil || msg.GasTipCap == nil {
			return nil, fmt.Errorf("step %d has unsupported value or missing native fee fields", i)
		}
		if msg.GasLimit != 12500000 || msg.GasPrice.Cmp(big.NewInt(1)) != 0 || msg.GasFeeCap.Sign() != 0 || msg.GasTipCap.Sign() != 0 {
			return nil, fmt.Errorf("step %d differs from fixed Stage 1 gas/fee settings", i)
		}
		if msg.SkipNonceChecks || msg.SkipFromEOACheck || len(msg.AccessList) != 0 {
			return nil, fmt.Errorf("step %d has unsupported account checks/access list", i)
		}
		if element.BlockNumberDelay != 0 || element.BlockTimestampDelay != 0 {
			return nil, fmt.Errorf("step %d has unsupported block delay", i)
		}
		if msg.Nonce != uint64(i) {
			return nil, fmt.Errorf("step %d nonce must be %d", i, i)
		}
		if msg.DataAbiValues != nil {
			if err := msg.DataAbiValues.Resolve(fx.ABI); err != nil {
				return nil, fmt.Errorf("step %d ABI resolve: %w", i, err)
			}
			packed, err := msg.DataAbiValues.Pack()
			if err != nil {
				return nil, err
			}
			if !bytes.Equal(packed, msg.Data) {
				return nil, fmt.Errorf("step %d raw calldata conflicts with ABI metadata", i)
			}
		}
		method, err := fx.ABI.MethodById(msg.Data)
		if err != nil || !fx.Allowed[method.Sig] {
			return nil, fmt.Errorf("step %d is not an allowed fixture operation", i)
		}
		values, err := method.Inputs.Unpack(msg.Data[4:])
		if err != nil {
			return nil, err
		}
		canonical, err := method.Inputs.Pack(values...)
		if err != nil || !bytes.Equal(canonical, msg.Data[4:]) {
			return nil, fmt.Errorf("step %d has noncanonical calldata", i)
		}
	}
	return seq, nil
}

func writeSequence(path string, seq calls.CallSequence) (string, error) {
	b, err := json.MarshalIndent(seq, "", "  ")
	if err != nil {
		return "", fmt.Errorf("native CallSequence encode: %w", err)
	}
	b = append(b, '\n')
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return "", err
	}
	if err := os.WriteFile(path, b, 0644); err != nil {
		return "", err
	}
	return sha256Hex(b), nil
}

func appendCandidate(seq calls.CallSequence, fx *fixture, decimal string) (calls.CallSequence, error) {
	if len(seq) < 1 || len(seq) > 3 {
		return nil, fmt.Errorf("candidate prefix must have 1..3 calls")
	}
	arg, ok := new(big.Int).SetString(decimal, 10)
	if !ok || arg.Sign() < 0 || arg.BitLen() > 256 || decimal == "" {
		return nil, fmt.Errorf("argument must be a decimal uint256")
	}
	for _, c := range decimal {
		if c < '0' || c > '9' {
			return nil, fmt.Errorf("argument must contain decimal digits only")
		}
	}
	last := seq[len(seq)-1]
	method, ok := fx.ABI.Methods[fx.Suffix]
	if !ok {
		return nil, fmt.Errorf("fixture lacks suffix")
	}
	data := &calls.CallMessageDataAbiValues{Method: &method, InputValues: []any{arg}}
	call := calls.NewCallMessageWithAbiValueData(last.Call.From, last.Call.To, last.Call.Nonce+1, big.NewInt(0), last.Call.GasLimit, new(big.Int).Set(last.Call.GasPrice), new(big.Int).Set(last.Call.GasFeeCap), new(big.Int).Set(last.Call.GasTipCap), data)
	return append(seq, calls.NewCallSequenceElement(nil, call, 0, 0)), nil
}

func sequenceSummary(seq calls.CallSequence) map[string]any {
	steps := []map[string]any{}
	for _, element := range seq {
		steps = append(steps, map[string]any{"from": element.Call.From.Hex(), "to": element.Call.To.Hex(), "nonce": element.Call.Nonce, "value": element.Call.Value.String(), "calldata": "0x" + hex.EncodeToString(element.Call.Data), "block_number_delay": element.BlockNumberDelay, "block_timestamp_delay": element.BlockTimestampDelay})
	}
	h, _ := seq.Hash()
	return map[string]any{"schema_version": 1, "medusa_version": medusaVersion, "medusa_hash": h.Hex(), "steps": steps}
}
