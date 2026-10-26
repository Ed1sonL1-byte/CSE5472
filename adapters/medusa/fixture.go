package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/crytic/medusa-geth/accounts/abi"
	"github.com/crytic/medusa-geth/common"
	"github.com/crytic/medusa-geth/crypto"
)

var actor = common.HexToAddress("0x10000")
var deployer = common.HexToAddress("0x30000")
var targetAddress = crypto.CreateAddress(deployer, 0)

type fixture struct {
	ID               string
	Contract         string
	Suffix           string
	Safety           bool
	PropertyID       string
	Root             string
	Project          string
	ArtifactPath     string
	SourcePath       string
	ABI              abi.ABI
	ArtifactABI      json.RawMessage
	Init             []byte
	Runtime          []byte
	Allowed          map[string]bool
	External         bool
	Getter           string
	RevertedExpected string
}

func repositoryRoot() (string, error) {
	starts := []string{}
	if cwd, err := os.Getwd(); err == nil {
		starts = append(starts, cwd)
	}
	if exe, err := os.Executable(); err == nil {
		starts = append(starts, filepath.Dir(exe))
	}
	for _, start := range starts {
		for dir := start; ; dir = filepath.Dir(dir) {
			// The proposal and legacy docs were removed. Anchor discovery to
			// files required by this adapter instead of an unrelated document.
			if _, err := os.Stat(filepath.Join(dir, "pyproject.toml")); err == nil {
				if _, err := os.Stat(filepath.Join(dir, "fixtures", "phase_counter", "src", "PhaseCounter.sol")); err == nil {
					return filepath.EvalSymlinks(dir)
				}
			}
			if filepath.Dir(dir) == dir {
				break
			}
		}
	}
	return "", fmt.Errorf("run inside the CSE5472 repository containing the fixed teaching fixtures")
}

func loadFixture(id string) (*fixture, error) {
	if _, external := externalTargets[id]; external {
		return loadExternalFixture(id)
	}
	return loadFixtureProject(id, "")
}

func loadFixtureProject(id string, project string) (*fixture, error) {
	f := &fixture{ID: id, Allowed: map[string]bool{}}
	switch id {
	case "phase_counter":
		f.Contract, f.Suffix = "PhaseCounter", "complete"
		f.Allowed["begin()"], f.Allowed["advance(uint256)"], f.Allowed["complete(uint256)"] = true, true, true
	case "bounded_ledger":
		f.Contract, f.Suffix = "BoundedLedger", "settle"
		f.Allowed["open()"], f.Allowed["reserve(uint256)"], f.Allowed["settle(uint256)"] = true, true, true
	case "range_gate":
		f.Contract, f.Suffix = "RangeGate", "passRange"
		f.Allowed["begin()"], f.Allowed["configure(uint256)"], f.Allowed["passRange(uint256)"] = true, true, true
	case "workflow_gate":
		f.Contract, f.Suffix = "WorkflowGate", "unlock"
		f.Allowed["start()"], f.Allowed["choose(uint256)"], f.Allowed["unlock(uint256)"], f.Allowed["continueWork(uint256)"] = true, true, true, true
	case "accounting_flawed":
		f.Contract, f.Suffix, f.Safety, f.PropertyID = "AccountingFlawed", "spend", true, "allocation_conservation"
		f.Allowed["open()"], f.Allowed["spend(uint256)"] = true, true
	case "accounting_repaired":
		f.Contract, f.Suffix, f.Safety, f.PropertyID = "AccountingRepaired", "spend", true, "allocation_conservation"
		f.Allowed["open()"], f.Allowed["spend(uint256)"] = true, true
	case "reservation_flawed":
		f.Contract, f.Suffix, f.Safety, f.PropertyID = "ReservationFlawed", "settle", true, "reservation_conservation"
		f.Allowed["start()"], f.Allowed["reserve(uint256)"], f.Allowed["settle(uint256)"] = true, true, true
	case "reservation_repaired":
		f.Contract, f.Suffix, f.Safety, f.PropertyID = "ReservationRepaired", "settle", true, "reservation_conservation"
		f.Allowed["start()"], f.Allowed["reserve(uint256)"], f.Allowed["settle(uint256)"] = true, true, true
	case "request_flawed":
		f.Contract, f.Suffix, f.Safety, f.PropertyID = "RequestFlawed", "confirm", true, "approval_bound"
		f.Allowed["start()"], f.Allowed["request(uint256)"], f.Allowed["confirm(uint256)"] = true, true, true
	case "request_repaired":
		f.Contract, f.Suffix, f.Safety, f.PropertyID = "RequestRepaired", "confirm", true, "approval_bound"
		f.Allowed["start()"], f.Allowed["request(uint256)"], f.Allowed["confirm(uint256)"] = true, true, true
	default:
		return nil, fmt.Errorf("unsupported fixture %q", id)
	}
	root, err := repositoryRoot()
	if err != nil {
		return nil, err
	}
	f.Root = root
	canonicalProject := filepath.Join(root, "fixtures", id)
	f.Project = canonicalProject
	if project != "" {
		absolute, err := filepath.Abs(project)
		if err != nil {
			return nil, err
		}
		f.Project = absolute
	}
	resolved, err := filepath.EvalSymlinks(f.Project)
	if err != nil {
		return nil, fmt.Errorf("fixture project must be a real directory: %s", f.Project)
	}
	f.Project = resolved
	f.SourcePath = filepath.Join(f.Project, "src", f.Contract+".sol")
	if project != "" {
		canonicalSource := filepath.Join(canonicalProject, "src", f.Contract+".sol")
		expectedSource, sourceErr := fileSHA(canonicalSource)
		actualSource, actualErr := fileSHA(f.SourcePath)
		expectedConfig, configErr := fileSHA(filepath.Join(canonicalProject, "foundry.toml"))
		actualConfig, actualConfigErr := fileSHA(filepath.Join(f.Project, "foundry.toml"))
		if sourceErr != nil || actualErr != nil || configErr != nil || actualConfigErr != nil || expectedSource != actualSource || expectedConfig != actualConfig {
			return nil, fmt.Errorf("fixture project source or Foundry config differs from built-in %s", id)
		}
	}
	f.ArtifactPath = filepath.Join(f.Project, "out", f.Contract+".sol", f.Contract+".json")
	data, err := os.ReadFile(f.ArtifactPath)
	if err != nil {
		return nil, fmt.Errorf("build the fixed fixture with forge first: %w", err)
	}
	var artifact struct {
		ABI      json.RawMessage `json:"abi"`
		Bytecode struct {
			Object string `json:"object"`
		} `json:"bytecode"`
		DeployedBytecode struct {
			Object string `json:"object"`
		} `json:"deployedBytecode"`
	}
	if err := json.Unmarshal(data, &artifact); err != nil {
		return nil, err
	}
	f.ABI, err = abi.JSON(strings.NewReader(string(artifact.ABI)))
	if err != nil {
		return nil, err
	}
	f.ArtifactABI = artifact.ABI
	f.Init, err = hex.DecodeString(strings.TrimPrefix(artifact.Bytecode.Object, "0x"))
	if err != nil {
		return nil, err
	}
	f.Runtime, err = hex.DecodeString(strings.TrimPrefix(artifact.DeployedBytecode.Object, "0x"))
	if err != nil {
		return nil, err
	}
	if len(f.Init) == 0 || len(f.Runtime) == 0 {
		return nil, fmt.Errorf("fixture artifact has empty bytecode")
	}
	return f, nil
}

func sha256Hex(data []byte) string { h := sha256.Sum256(data); return hex.EncodeToString(h[:]) }

func fileSHA(path string) (string, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	return sha256Hex(b), nil
}
