package main

import (
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math/big"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/crytic/medusa-geth/accounts/abi"
	"github.com/crytic/medusa-geth/common"
	gethTypes "github.com/crytic/medusa-geth/core/types"
	"github.com/crytic/medusa-geth/crypto"
	"github.com/crytic/medusa/chain"
	chainconfig "github.com/crytic/medusa/chain/config"
	"github.com/crytic/medusa/fuzzing/calls"
	"github.com/holiman/uint256"
)

// externalTarget describes one unchanged Solidity 0.4.x benchmark contract.
// The observer reads a public getter from a separate, discarded call. It does
// not require observe(), invariantHolds(), or propertyHolds() on the target.
type externalTarget struct {
	ID               string
	Contract         string
	SourceFile       string
	Solc             string
	EVMVersion       string
	Allowed          []string
	Getter           string
	PropertyID       string
	SourceSHA256     string
	InitSHA256       string
	RuntimeSHA256    string
	RevertedExpected string
}

var externalTargets = map[string]externalTarget{
	"sb_multitx_onefunc": {
		ID: "sb_multitx_onefunc", Contract: "IntegerOverflowMultiTxOneFuncFeasible",
		SourceFile: "integer_overflow_multitx_onefunc_feasible.sol",
		Solc:       "0.4.26", EVMVersion: "byzantium", Getter: "count",
		Allowed: []string{"run(uint256)"}, PropertyID: "count_after_subtraction_at_most_initial",
		SourceSHA256:  "2467c66a24f705b43c93495ffe8c065659507d2f2ff00d6affb9a72344606869",
		InitSHA256:    "c700452a7ce1c5a76c249d38292467936ca28b46181fc4b6d2d8c43e17db020f",
		RuntimeSHA256: "4870f963b1ba31a6bffd2a2be1be88a6bacbf847cbe4c65162ac7b3c69110468",
	},
	"sb_multitx_multifunc": {
		ID: "sb_multitx_multifunc", Contract: "IntegerOverflowMultiTxMultiFuncFeasible",
		SourceFile: "integer_overflow_multitx_multifunc_feasible.sol",
		Solc:       "0.4.26", EVMVersion: "byzantium", Getter: "count",
		Allowed: []string{"init()", "run(uint256)"}, PropertyID: "count_after_subtraction_at_most_initial",
		SourceSHA256:  "b4751ff85a668932e084d03b08992f62b85f3a62dea2224d7f93eafe5628188f",
		InitSHA256:    "8721c06b65873de26c482232130694c2933c00bb7e2d62cb40f10e8c7f9bbc96",
		RuntimeSHA256: "41c39ee51736cf43185b9763bacdcba81d7eed56feb1a6d3ef83cf81fee9bd19",
	},
	"sb_overflow_benign": {
		ID: "sb_overflow_benign", Contract: "IntegerOverflowBenign1",
		SourceFile: "integer_overflow_benign_1.sol",
		Solc:       "0.4.26", EVMVersion: "byzantium", Getter: "count",
		Allowed: []string{"run(uint256)"}, PropertyID: "local_arithmetic_preserves_count",
		SourceSHA256:  "7f05171b2d6c4611145729a0444d31d7e07d70743995520df4641f17929495c3",
		InitSHA256:    "06e733c70b25895cff6870ce6fdf75a7f964c680b4c88ee7d4661a9739c5023a",
		RuntimeSHA256: "ddcb385940ab9031b9ffe4f21ac5af4331e33f6da48d2d2b514fb806b0c1cf92",
	},
}

func externalScenario(id string) bool {
	_, ok := externalTargets[id]
	return ok
}

func loadExternalFixture(id string) (*fixture, error) {
	spec, ok := externalTargets[id]
	if !ok {
		return nil, fmt.Errorf("unsupported external scenario %q", id)
	}
	root, err := repositoryRoot()
	if err != nil {
		return nil, err
	}
	sourcePath := filepath.Join(root, "evidence", "stage6", "pinned", "sb-heists-ac0fbc2", "dataset", "arithmetic", "sources", spec.SourceFile)
	source, err := os.ReadFile(sourcePath)
	if err != nil {
		return nil, err
	}
	if sha256Hex(source) != spec.SourceSHA256 {
		return nil, fmt.Errorf("pinned external source hash changed: %s", spec.SourceFile)
	}
	compiled, err := compileExternal(spec, source)
	if err != nil {
		return nil, err
	}
	if sha256Hex(compiled.Init) != spec.InitSHA256 || sha256Hex(compiled.Runtime) != spec.RuntimeSHA256 {
		return nil, fmt.Errorf("external bytecode hash changed for %s", id)
	}
	allowed := map[string]bool{}
	for _, signature := range spec.Allowed {
		allowed[signature] = true
	}
	if _, ok := compiled.ABI.Methods[spec.Getter]; !ok {
		return nil, fmt.Errorf("external contract %s has no public %s getter", spec.Contract, spec.Getter)
	}
	return &fixture{
		ID: id, Contract: spec.Contract, Suffix: "run", Safety: true, PropertyID: spec.PropertyID,
		External: true, Getter: spec.Getter, RevertedExpected: "none",
		Root: root, Project: filepath.Dir(sourcePath), SourcePath: sourcePath,
		ABI: compiled.ABI, ArtifactABI: compiled.ABIJSON,
		Init: compiled.Init, Runtime: compiled.Runtime, Allowed: allowed,
	}, nil
}

type externalCompilation struct {
	ABI     abi.ABI
	ABIJSON json.RawMessage
	Init    []byte
	Runtime []byte
}

func compileExternal(spec externalTarget, source []byte) (externalCompilation, error) {
	var compiled externalCompilation
	if spec.Solc != "0.4.26" || spec.EVMVersion != "byzantium" {
		return compiled, fmt.Errorf("unsupported external compiler request")
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return compiled, err
	}
	solc := filepath.Join(home, ".solc-select", "artifacts", "solc-0.4.26", "solc-0.4.26")
	payload := map[string]any{
		"language": "Solidity",
		"sources":  map[string]any{spec.SourceFile: map[string]string{"content": string(source)}},
		"settings": map[string]any{
			"optimizer":  map[string]any{"enabled": false},
			"evmVersion": spec.EVMVersion,
			"outputSelection": map[string]any{
				"*": map[string][]string{"*": {"abi", "evm.bytecode.object", "evm.deployedBytecode.object"}},
			},
		},
	}
	input, err := json.Marshal(payload)
	if err != nil {
		return compiled, err
	}
	command := exec.Command("arch", "-x86_64", solc, "--standard-json")
	command.Stdin = bytes.NewReader(input)
	output, err := command.Output()
	if err != nil {
		return compiled, fmt.Errorf("solc 0.4.26 standard JSON failed: %w", err)
	}
	var document struct {
		Errors []struct {
			Severity, Message, Type string
		} `json:"errors"`
		Contracts map[string]map[string]struct {
			ABI json.RawMessage `json:"abi"`
			EVM struct {
				Bytecode         struct{ Object string } `json:"bytecode"`
				DeployedBytecode struct{ Object string } `json:"deployedBytecode"`
			} `json:"evm"`
		} `json:"contracts"`
	}
	if err := json.Unmarshal(output, &document); err != nil {
		return compiled, err
	}
	for _, item := range document.Errors {
		if item.Severity == "error" || item.Type == "JSONError" {
			return compiled, fmt.Errorf("solc error: %s", item.Message)
		}
	}
	fileContracts := document.Contracts[spec.SourceFile]
	contract, ok := fileContracts[spec.Contract]
	if !ok || len(fileContracts) != 1 {
		return compiled, fmt.Errorf("standard JSON did not return only %s", spec.Contract)
	}
	compiled.ABIJSON = contract.ABI
	compiled.ABI, err = abi.JSON(bytes.NewReader(contract.ABI))
	if err != nil {
		return compiled, err
	}
	compiled.Init, err = hex.DecodeString(strings.TrimPrefix(contract.EVM.Bytecode.Object, "0x"))
	if err != nil {
		return compiled, err
	}
	compiled.Runtime, err = hex.DecodeString(strings.TrimPrefix(contract.EVM.DeployedBytecode.Object, "0x"))
	if err != nil {
		return compiled, err
	}
	if len(compiled.Init) == 0 || len(compiled.Runtime) == 0 {
		return compiled, fmt.Errorf("external compilation returned empty bytecode")
	}
	return compiled, nil
}

func observeExternal(fx *fixture, testChain *chain.TestChain, step *stepRecord) error {
	if !fx.External {
		return fmt.Errorf("external observer used for an owned fixture")
	}
	before := testChain.State().IntermediateRoot(false)
	count, raw, err := readView(testChain, fx, fx.Getter)
	if err != nil {
		return err
	}
	if len(count) != 1 {
		return fmt.Errorf("external getter %s must return one value", fx.Getter)
	}
	value, ok := count[0].(*big.Int)
	if !ok || value.Sign() < 0 || value.BitLen() > 256 {
		return fmt.Errorf("external getter %s did not return uint256", fx.Getter)
	}
	after := testChain.State().IntermediateRoot(false)
	if before != after {
		return fmt.Errorf("external observer changed persistent state")
	}
	canonical := value.String()
	step.Observe = []any{canonical, "0", "0", false}
	step.StateDigest = sha256Hex(raw)
	if step.StateRootBeforeObserver == "" {
		step.StateRootBeforeObserver = before.Hex()
	} else if step.StateRootBeforeObserver != before.Hex() {
		return fmt.Errorf("external observer root differs from the post-call root")
	}
	step.StateRootAfterObserver = after.Hex()
	step.ObserverStateUnchanged = true
	holds, err := externalProperty(fx.PropertyID, canonical, step.Success, step.Signature)
	if err != nil {
		return err
	}
	step.PropertyHolds = &holds
	goal := !holds
	step.Goal = &goal
	step.Observe[3] = goal
	unchanged := true
	step.InvariantHolds = &unchanged
	return nil
}

func externalProperty(propertyID, count string, success bool, signature string) (bool, error) {
	value, ok := new(big.Int).SetString(count, 10)
	if !ok {
		return false, fmt.Errorf("external count is not decimal")
	}
	initial := big.NewInt(1)
	switch propertyID {
	case "count_after_subtraction_at_most_initial":
		if success && signature == "run(uint256)" && value.Cmp(initial) > 0 {
			return false, nil
		}
		return true, nil
	case "local_arithmetic_preserves_count":
		if success && signature == "run(uint256)" && value.Cmp(initial) != 0 {
			return false, nil
		}
		return true, nil
	default:
		return false, fmt.Errorf("unsupported external property %q", propertyID)
	}
}

func externalCalldata(fx *fixture, signature string, argument *big.Int) ([]byte, error) {
	if !fx.Allowed[signature] {
		return nil, fmt.Errorf("signature %s is not allowed", signature)
	}
	method, err := methodBySignature(fx, signature)
	if err != nil {
		return nil, err
	}
	if len(method.Inputs) == 0 {
		return method.ID, nil
	}
	if len(method.Inputs) != 1 || argument == nil {
		return nil, fmt.Errorf("signature %s requires one uint256", signature)
	}
	packed, err := method.Inputs.Pack(argument)
	if err != nil {
		return nil, err
	}
	return append(append([]byte{}, method.ID...), packed...), nil
}

func methodBySignature(fx *fixture, signature string) (abi.Method, error) {
	for _, method := range fx.ABI.Methods {
		if method.Sig == signature {
			return method, nil
		}
	}
	return abi.Method{}, fmt.Errorf("ABI has no %s", signature)
}

type externalStep struct {
	Signature string `json:"signature"`
	Argument  string `json:"argument,omitempty"`
}

type externalReplayRequest struct {
	Steps []externalStep `json:"steps"`
}

func replayExternal(fx *fixture, inputPath, outputPath string) error {
	if !fx.External {
		return fmt.Errorf("replay-external requires an external scenario")
	}
	raw, err := os.ReadFile(inputPath)
	if err != nil {
		return err
	}
	var request externalReplayRequest
	if err := json.Unmarshal(raw, &request); err != nil {
		return err
	}
	if len(request.Steps) < 1 || len(request.Steps) > 5 {
		return fmt.Errorf("external replay requires 1..5 calls")
	}
	config, err := chainconfig.DefaultTestChainConfig()
	if err != nil {
		return err
	}
	config.CheatCodeConfig.CheatCodesEnabled = false
	config.CodeSizeCheckDisabled = false
	config.SkipAccountChecks = false
	balance := new(uint256.Int).Lsh(uint256.NewInt(1), 100)
	testChain, err := chain.NewTestChain(context.Background(), gethTypes.GenesisAlloc{
		deployer: {Balance: balance.ToBig()},
		actor:    {Balance: balance.ToBig()},
	}, config)
	if err != nil {
		return err
	}
	defer testChain.Close()
	testChain.BlockGasLimit = 12500000
	if err := commitExternal(testChain, deployer, nil, fx.Init, 0); err != nil {
		return err
	}
	if crypto.CreateAddress(deployer, 0) != targetAddress {
		return fmt.Errorf("external deployment address differs from the fixed target")
	}
	if !bytes.Equal(testChain.State().GetCode(targetAddress), fx.Runtime) {
		return fmt.Errorf("deployed runtime differs from the pinned artifact")
	}
	steps := []stepRecord{}
	for index, item := range request.Steps {
		var argument *big.Int
		if item.Argument != "" {
			parsed, ok := new(big.Int).SetString(item.Argument, 10)
			if !ok || parsed.Sign() < 0 || parsed.BitLen() > 256 {
				return fmt.Errorf("step %d argument is not a uint256", index)
			}
			argument = parsed
		}
		data, err := externalCalldata(fx, item.Signature, argument)
		if err != nil {
			return err
		}
		if err := commitExternal(testChain, actor, &targetAddress, data, uint64(index)); err != nil {
			return err
		}
		block := testChain.Head()
		result := block.MessageResults[len(block.MessageResults)-1]
		method, err := fx.ABI.MethodById(data)
		if err != nil {
			return err
		}
		decoded, err := method.Inputs.Unpack(data[4:])
		if err != nil {
			return err
		}
		arguments := make([]string, len(decoded))
		for i, value := range decoded {
			arguments[i] = fmt.Sprint(value)
		}
		step := stepRecord{
			Index: index, From: actor.Hex(), To: targetAddress.Hex(), Nonce: uint64(index),
			Value: "0", Calldata: "0x" + hex.EncodeToString(data), Signature: method.Sig,
			Arguments: arguments, Success: result.ExecutionResult.Err == nil && result.Receipt.Status == 1,
			BlockNumber: block.Header.Number.Uint64(), BlockTimestamp: block.Header.Time,
			GasUsed: result.Receipt.GasUsed, ReturnData: "0x" + hex.EncodeToString(result.ExecutionResult.Return()),
			CoverageDigest: "external-replay-not-a-fuzzer-prefix", CumulativeCoverageDigest: "external-replay-not-a-fuzzer-prefix",
		}
		step.Status = "success"
		if !step.Success {
			step.Status = "revert"
		}
		if err := observeExternal(fx, testChain, &step); err != nil {
			return err
		}
		steps = append(steps, step)
	}
	report := map[string]any{
		"schema_version": 1, "mode": "external_direct_replay", "fixture": fx.ID,
		"contract": fx.Contract, "property_id": fx.PropertyID, "repaired_counterpart": "none",
		"observer": fx.Getter + "()", "observer_mutates_state": false,
		"fuzzer_prefix": false, "target": targetAddress.Hex(), "actor": actor.Hex(),
		"deployer": deployer.Hex(), "source_sha256": sha256Hex(mustRead(fx.SourcePath)),
		"init_bytecode_sha256": sha256Hex(fx.Init), "runtime_bytecode_sha256": sha256Hex(fx.Runtime),
		"compiler": "solc 0.4.26+commit.4563c3fc", "optimizer": false, "evm_version": "byzantium",
		"chain_rule": "medusa-v1.5.1 TestChain with Shanghai time 0",
		"steps":      steps,
	}
	return writeJSON(outputPath, report)
}

func commitExternal(testChain *chain.TestChain, from common.Address, to *common.Address, data []byte, nonce uint64) error {
	if _, err := testChain.PendingBlockCreate(); err != nil {
		return err
	}
	message := calls.NewCallMessage(from, to, nonce, big.NewInt(0), 4000000, big.NewInt(1), big.NewInt(1), big.NewInt(1), data)
	if err := testChain.PendingBlockAddTx(message.ToCoreMessage()); err != nil {
		return err
	}
	return testChain.PendingBlockCommit()
}

func mustRead(path string) []byte {
	data, err := os.ReadFile(path)
	if err != nil {
		panic(err)
	}
	return data
}

func externalSequence(fx *fixture, callsData [][]byte) calls.CallSequence {
	sequence := make(calls.CallSequence, len(callsData))
	for index, data := range callsData {
		message := calls.NewCallMessage(actor, &targetAddress, uint64(index), big.NewInt(0), 12500000, big.NewInt(1), big.NewInt(0), big.NewInt(0), data)
		sequence[index] = calls.NewCallSequenceElement(nil, message, 0, 0)
	}
	return sequence
}
