package main

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math/big"
	"os"
	"path/filepath"
	"strings"

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
	if len(seq) < 1 || len(seq) > 5 {
		return nil, fmt.Errorf("native sequence must have 1..5 calls")
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
		if !externalGasAccepted(fx, msg) {
			return nil, fmt.Errorf("step %d differs from the scenario gas/fee settings", i)
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

func externalGasAccepted(fx *fixture, msg *calls.CallMessage) bool {
	if msg.GasPrice.Cmp(big.NewInt(1)) != 0 {
		return false
	}
	if fx.External {
		return msg.GasLimit == 4_000_000 && msg.GasFeeCap.Sign() == 0 && msg.GasTipCap.Sign() == 0
	}
	return msg.GasLimit == 12_500_000 && msg.GasFeeCap.Sign() == 0 && msg.GasTipCap.Sign() == 0
}

func writeSequence(path string, seq calls.CallSequence) (string, error) {
	b, digest, err := marshalSequence(seq)
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return "", err
	}
	if err := os.WriteFile(path, b, 0644); err != nil {
		return "", err
	}
	return digest, nil
}

func marshalSequence(seq calls.CallSequence) ([]byte, string, error) {
	b, err := json.MarshalIndent(seq, "", "  ")
	if err != nil {
		return nil, "", fmt.Errorf("native CallSequence encode: %w", err)
	}
	b = append(b, '\n')
	return b, sha256Hex(b), nil
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

type suffixCallRequest struct {
	Signature       string  `json:"signature"`
	Selector        string  `json:"selector"`
	Argument        *string `json:"argument"`
	Actor           string  `json:"actor"`
	Target          string  `json:"target"`
	Value           string  `json:"value"`
	ActualBlock     string  `json:"actual_block"`
	ActualTimestamp string  `json:"actual_timestamp"`
}

type suffixPlanRequest struct {
	Calls []suffixCallRequest `json:"calls"`
}

func appendSuffixCalls(seq calls.CallSequence, fx *fixture, request suffixPlanRequest) (calls.CallSequence, error) {
	if len(seq) < 1 || len(seq) > 3 || len(request.Calls) < 1 || len(request.Calls) > 2 || len(seq)+len(request.Calls) > 5 {
		return nil, fmt.Errorf("suffix requires a 1..3-call prefix, 1..2 new calls, and at most five total calls")
	}
	last := seq[len(seq)-1]
	for index, entry := range request.Calls {
		if !fx.Allowed[entry.Signature] || entry.Value != "0" ||
			!strings.EqualFold(entry.Actor, last.Call.From.Hex()) ||
			!strings.EqualFold(entry.Target, last.Call.To.Hex()) {
			return nil, fmt.Errorf("suffix call %d has an unsupported signature, actor, target, or value", index)
		}
		for _, context := range []string{entry.ActualBlock, entry.ActualTimestamp} {
			value, ok := new(big.Int).SetString(context, 10)
			if !ok || value.Sign() < 0 || value.BitLen() > 256 {
				return nil, fmt.Errorf("suffix call %d has invalid execution context", index)
			}
		}
		if index > 0 && (entry.ActualBlock != request.Calls[0].ActualBlock || entry.ActualTimestamp != request.Calls[0].ActualTimestamp) {
			return nil, fmt.Errorf("suffix context differs despite fixed zero block delays")
		}
		methodName := strings.SplitN(entry.Signature, "(", 2)[0]
		method, ok := fx.ABI.Methods[methodName]
		if !ok || method.Sig != entry.Signature || !strings.EqualFold(entry.Selector, "0x"+hex.EncodeToString(method.ID)) {
			return nil, fmt.Errorf("suffix call %d method or selector differs from the ABI", index)
		}
		values := []any{}
		if len(method.Inputs) == 0 {
			if entry.Argument != nil {
				return nil, fmt.Errorf("suffix call %d supplies an argument to a no-arg method", index)
			}
		} else if len(method.Inputs) == 1 && method.Inputs[0].Type.String() == "uint256" {
			if entry.Argument == nil || *entry.Argument == "" {
				return nil, fmt.Errorf("suffix call %d lacks its uint256 argument", index)
			}
			for _, c := range *entry.Argument {
				if c < '0' || c > '9' {
					return nil, fmt.Errorf("suffix call %d argument is not decimal", index)
				}
			}
			arg, ok := new(big.Int).SetString(*entry.Argument, 10)
			if !ok || arg.Sign() < 0 || arg.BitLen() > 256 || (len(*entry.Argument) > 1 && (*entry.Argument)[0] == '0') {
				return nil, fmt.Errorf("suffix call %d argument is not canonical uint256", index)
			}
			values = append(values, arg)
		} else {
			return nil, fmt.Errorf("suffix call %d has an unsupported ABI", index)
		}
		data := &calls.CallMessageDataAbiValues{Method: &method, InputValues: values}
		call := calls.NewCallMessageWithAbiValueData(last.Call.From, last.Call.To, last.Call.Nonce+1,
			big.NewInt(0), last.Call.GasLimit, new(big.Int).Set(last.Call.GasPrice),
			new(big.Int).Set(last.Call.GasFeeCap), new(big.Int).Set(last.Call.GasTipCap), data)
		seq = append(seq, calls.NewCallSequenceElement(nil, call, 0, 0))
		last = seq[len(seq)-1]
	}
	return seq, nil
}

func encodeSuffix(inputPath string, planPath string, outputPath string, fx *fixture) error {
	sequence, err := readSequence(inputPath, fx)
	if err != nil {
		return err
	}
	data, err := os.ReadFile(planPath)
	if err != nil {
		return err
	}
	var request suffixPlanRequest
	if err := json.Unmarshal(data, &request); err != nil {
		return fmt.Errorf("suffix plan decode: %w", err)
	}
	sequence, err = appendSuffixCalls(sequence, fx, request)
	if err != nil {
		return err
	}
	_, err = writeSequence(outputPath, sequence)
	return err
}

func sequenceSummary(seq calls.CallSequence) map[string]any {
	steps := []map[string]any{}
	for _, element := range seq {
		steps = append(steps, map[string]any{"from": element.Call.From.Hex(), "to": element.Call.To.Hex(), "nonce": element.Call.Nonce, "value": element.Call.Value.String(), "calldata": "0x" + hex.EncodeToString(element.Call.Data), "block_number_delay": element.BlockNumberDelay, "block_timestamp_delay": element.BlockTimestampDelay})
	}
	h, _ := seq.Hash()
	return map[string]any{"schema_version": 1, "medusa_version": medusaVersion, "medusa_hash": h.Hex(), "steps": steps}
}

type batchCandidateRequest struct {
	Input    string `json:"input"`
	Output   string `json:"output"`
	Argument string `json:"argument"`
}

func encodeCandidateBatch(planPath string, outputPath string, fx *fixture) error {
	data, err := os.ReadFile(planPath)
	if err != nil {
		return err
	}
	var requests []batchCandidateRequest
	if err := json.Unmarshal(data, &requests); err != nil {
		return fmt.Errorf("candidate batch plan decode: %w", err)
	}
	if len(requests) < 1 || len(requests) > 256 {
		return fmt.Errorf("candidate batch must contain 1..256 entries")
	}
	seen := map[string]bool{}
	results := make([]map[string]any, 0, len(requests))
	for index, request := range requests {
		input, err := filepath.Abs(request.Input)
		if err != nil {
			return err
		}
		output, err := filepath.Abs(request.Output)
		if err != nil {
			return err
		}
		if seen[output] {
			return fmt.Errorf("duplicate batch output at index %d", index)
		}
		seen[output] = true
		if _, err := os.Stat(output); err == nil {
			return fmt.Errorf("batch output already exists: %s", output)
		}
		sequence, err := readSequence(input, fx)
		if err != nil {
			return fmt.Errorf("batch input %d: %w", index, err)
		}
		sequence, err = appendCandidate(sequence, fx, request.Argument)
		if err != nil {
			return fmt.Errorf("batch argument %d: %w", index, err)
		}
		digest, err := writeSequence(output, sequence)
		if err != nil {
			return err
		}
		results = append(results, map[string]any{
			"index": index, "input": input, "native_path": output,
			"native_sha256": digest, "argument": request.Argument,
			"summary": sequenceSummary(sequence),
		})
	}
	return writeJSON(outputPath, map[string]any{
		"schema_version": 1, "fixture": fx.ID, "entries": results,
	})
}
