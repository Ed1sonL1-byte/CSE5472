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
	ID           string
	Contract     string
	Suffix       string
	Root         string
	Project      string
	ArtifactPath string
	SourcePath   string
	ABI          abi.ABI
	ArtifactABI  json.RawMessage
	Init         []byte
	Runtime      []byte
	Allowed      map[string]bool
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
			if _, err := os.Stat(filepath.Join(dir, "output", "pdf", "symbolic-seed-proposal.md")); err == nil {
				return filepath.EvalSymlinks(dir)
			}
			if filepath.Dir(dir) == dir {
				break
			}
		}
	}
	return "", fmt.Errorf("run inside the CSE5472 repository containing the fixed teaching fixtures")
}

func loadFixture(id string) (*fixture, error) {
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
	default:
		return nil, fmt.Errorf("unsupported fixture %q; choose phase_counter, bounded_ledger, range_gate, or workflow_gate", id)
	}
	root, err := repositoryRoot()
	if err != nil {
		return nil, err
	}
	f.Root, f.Project = root, filepath.Join(root, "fixtures", id)
	resolved, err := filepath.EvalSymlinks(f.Project)
	if err != nil || resolved != f.Project {
		return nil, fmt.Errorf("fixture project must be a real repository directory: %s", f.Project)
	}
	f.SourcePath = filepath.Join(f.Project, "src", f.Contract+".sol")
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
