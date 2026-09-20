package main

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math/big"
	"math/rand"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"sort"
	"strings"
	"sync/atomic"
	"time"

	"github.com/crytic/medusa-geth/core/tracing"
	"github.com/crytic/medusa-geth/eth/tracers"
	"github.com/crytic/medusa/chain"
	chainTypes "github.com/crytic/medusa/chain/types"
	"github.com/crytic/medusa/compilation/platforms"
	"github.com/crytic/medusa/fuzzing"
	"github.com/crytic/medusa/fuzzing/calls"
	"github.com/crytic/medusa/fuzzing/config"
	"github.com/crytic/medusa/fuzzing/coverage"
	"github.com/crytic/medusa/fuzzing/valuegeneration"
	"github.com/rs/zerolog"
)

type runOptions struct {
	Output, CorpusDir, LineageOutput string
	Seed                             int64
	Tests, MaxSteps                  int
	Timeout                          time.Duration
	Observe, Campaign, RecordLineage bool
}

type stepRecord struct {
	Index                      int               `json:"index"`
	From                       string            `json:"from"`
	To                         string            `json:"to"`
	Nonce                      uint64            `json:"nonce"`
	Value                      string            `json:"value"`
	Calldata                   string            `json:"calldata"`
	Signature                  string            `json:"signature"`
	Arguments                  []string          `json:"arguments"`
	Status                     string            `json:"status"`
	Success                    bool              `json:"success"`
	BlockNumber                uint64            `json:"block_number"`
	BlockTimestamp             uint64            `json:"block_timestamp"`
	GasUsed                    uint64            `json:"gas_used"`
	ReturnData                 string            `json:"return_data"`
	Observe                    []any             `json:"observe"`
	Goal                       *bool             `json:"goal"`
	InvariantHolds             *bool             `json:"invariant_holds"`
	StateDigest                string            `json:"state_digest_sha256,omitempty"`
	StateRootBeforeObserver    string            `json:"state_root_before_observer"`
	StateRootAfterObserver     string            `json:"state_root_after_observer"`
	ObserverStateUnchanged     bool              `json:"observer_state_unchanged"`
	CoverageBranches           uint64            `json:"coverage_branches"`
	CumulativeCoverageBranches uint64            `json:"cumulative_coverage_branches"`
	CoverageDigest             string            `json:"coverage_digest_sha256"`
	CumulativeCoverageDigest   string            `json:"cumulative_coverage_digest_sha256"`
	CoverageMarkers            []string          `json:"coverage_markers"`
	CumulativeCoverageMarkers  []string          `json:"cumulative_coverage_markers"`
	CoverageMarkerHits         map[string]uint64 `json:"coverage_marker_hits"`
	CumulativeCoverageHits     map[string]uint64 `json:"cumulative_coverage_marker_hits"`
}

type sequenceRecord struct {
	SequenceIndex     int            `json:"sequence_index"`
	Origin            string         `json:"origin"`
	SourceNativePath  string         `json:"source_native_path,omitempty"`
	NativePath        string         `json:"native_path"`
	NativeDigest      string         `json:"native_digest"`
	MedusaHash        string         `json:"medusa_hash"`
	Steps             []stepRecord   `json:"steps"`
	Complete          bool           `json:"is_complete_sequence"`
	Replayed          bool           `json:"replayed_by_medusa"`
	Admitted          bool           `json:"admitted_for_mutation"`
	AdmissionStatus   string         `json:"admission_status"`
	AdmissionEvidence map[string]any `json:"admission_evidence,omitempty"`
}

type runReport struct {
	SchemaVersion      int                `json:"schema_version"`
	AdapterVersion     string             `json:"adapter_version"`
	MedusaVersion      string             `json:"medusa_version"`
	GoVersion          string             `json:"go_version"`
	Fixture            string             `json:"fixture"`
	Mode               string             `json:"mode"`
	Seed               int64              `json:"seed"`
	RNGStrategy        string             `json:"rng_strategy"`
	ObserverEnabled    bool               `json:"observer_enabled"`
	WorkerCount        int                `json:"worker_count"`
	MaxSteps           int                `json:"max_steps"`
	CompletedSequences int                `json:"completed_sequences"`
	ImportedSequences  int                `json:"imported_sequences"`
	TimedOut           bool               `json:"timed_out"`
	Status             string             `json:"status"`
	Error              string             `json:"error,omitempty"`
	CorpusDirectory    string             `json:"corpus_directory"`
	Deployment         map[string]any     `json:"deployment"`
	Build              map[string]any     `json:"build"`
	ConfigPath         string             `json:"config_path"`
	Sequences          []*sequenceRecord  `json:"sequences"`
	CoverageBranches   uint64             `json:"coverage_branches"`
	CoverageDigest     string             `json:"coverage_digest_sha256"`
	ElapsedSeconds     float64            `json:"elapsed_seconds"`
	GeneratorConfig    map[string]any     `json:"generator_config,omitempty"`
	StartupReplays     int                `json:"startup_replays"`
	NewSequences       int                `json:"new_sequences"`
	MutationSequences  int                `json:"mutation_sequences"`
	LineagePath        string             `json:"lineage_path,omitempty"`
	Lineage            []lineageRecord    `json:"lineage,omitempty"`
	LineageEnabled     bool               `json:"lineage_enabled"`
	CoverageMarkers    []string           `json:"coverage_markers"`
	CoverageMarkerHits map[string]uint64  `json:"coverage_marker_hits"`
	NativeTiming       map[string]float64 `json:"native_timing_seconds,omitempty"`
}

type importedSequence struct {
	Path, Hash, Identity string
	Length               int
}

type lineageRecord struct {
	GenerationID      uint64   `json:"generation_id"`
	SequenceIndex     int      `json:"sequence_index"`
	Kind              string   `json:"kind"`
	Strategy          string   `json:"strategy"`
	ParentHashes      []string `json:"parent_hashes"`
	ParentIdentities  []string `json:"parent_identity_hashes,omitempty"`
	OutputHash        string   `json:"output_hash"`
	OutputIdentity    string   `json:"output_identity_hash"`
	ImportedParent    bool     `json:"imported_parent"`
	ParentsResolved   bool     `json:"parents_resolved"`
	DifferentChild    bool     `json:"different_child"`
	Executed          bool     `json:"executed"`
	ExecutionStatuses []string `json:"execution_statuses"`
	GoalReached       bool     `json:"goal_reached"`
	CoverageBranches  uint64   `json:"coverage_branches"`
	CoverageDigest    string   `json:"coverage_digest_sha256"`
	StateDigest       string   `json:"state_digest_sha256,omitempty"`
	CompletedOffset   float64  `json:"completed_offset_seconds"`
}

type callIdentity struct {
	From     string `json:"from"`
	To       string `json:"to"`
	Value    string `json:"value"`
	Calldata string `json:"calldata"`
}

func identityDigest(identities []callIdentity) (string, error) {
	encoded, err := json.Marshal(identities)
	if err != nil {
		return "", err
	}
	return sha256Hex(encoded), nil
}

func nativeSequenceIdentity(sequence calls.CallSequence) (string, error) {
	identities := make([]callIdentity, len(sequence))
	for index, element := range sequence {
		if element == nil || element.Call == nil || element.Call.To == nil || element.Call.Value == nil {
			return "", fmt.Errorf("sequence identity requires a concrete call at index %d", index)
		}
		identities[index] = callIdentity{
			From: element.Call.From.Hex(), To: element.Call.To.Hex(), Value: element.Call.Value.String(),
			Calldata: "0x" + hex.EncodeToString(element.Call.Data),
		}
	}
	return identityDigest(identities)
}

func stepSequenceIdentity(steps []stepRecord) (string, error) {
	identities := make([]callIdentity, len(steps))
	for index, step := range steps {
		identities[index] = callIdentity{From: step.From, To: step.To, Value: step.Value, Calldata: step.Calldata}
	}
	return identityDigest(identities)
}

func writeJSONLines(path string, records []lineageRecord) error {
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0644)
	if err != nil {
		return err
	}
	encoder := json.NewEncoder(file)
	for _, record := range records {
		if err := encoder.Encode(record); err != nil {
			_ = file.Close()
			return err
		}
	}
	return file.Close()
}

func runObserved(fx *fixture, opts runOptions) error {
	runStarted := time.Now()
	if err := os.MkdirAll(filepath.Dir(opts.Output), 0755); err != nil {
		return err
	}
	if err := os.MkdirAll(opts.CorpusDir, 0755); err != nil {
		return err
	}
	nativeDir := strings.TrimSuffix(opts.Output, filepath.Ext(opts.Output)) + ".native"
	if err := os.Mkdir(nativeDir, 0755); err != nil {
		return fmt.Errorf("native evidence directory must be new: %w", err)
	}
	imports := []importedSequence{}
	paths, err := filepath.Glob(filepath.Join(opts.CorpusDir, "call_sequences", "*.json"))
	if err != nil {
		return err
	}
	for _, path := range paths {
		seq, err := readSequence(path, fx)
		if err != nil {
			return fmt.Errorf("reject corpus %s: %w", path, err)
		}
		h, err := seq.Hash()
		if err != nil {
			return err
		}
		identity, err := nativeSequenceIdentity(seq)
		if err != nil {
			return err
		}
		imports = append(imports, importedSequence{Path: path, Hash: h.Hex(), Identity: identity, Length: len(seq)})
	}
	if other, _ := filepath.Glob(filepath.Join(opts.CorpusDir, "test_results", "*.json")); len(other) != 0 {
		return fmt.Errorf("Stage 1 adapter does not accept test_results corpus")
	}
	if len(imports) > 0 && !opts.Campaign && opts.Tests != len(imports) {
		return fmt.Errorf("restart runs require --tests equal to imported sequence count (%d)", len(imports))
	}
	if opts.Campaign && opts.Tests <= len(imports) {
		return fmt.Errorf("campaign requires --tests greater than imported sequence count (%d)", len(imports))
	}
	projectConfig, err := config.GetDefaultProjectConfig("crytic-compile")
	if err != nil {
		return err
	}
	projectConfig.Fuzzing.Workers = 1
	projectConfig.Fuzzing.WorkerResetLimit = opts.Tests + 1
	projectConfig.Fuzzing.TestLimit = 0
	projectConfig.Fuzzing.Timeout = 0
	projectConfig.Fuzzing.CallSequenceLength = opts.MaxSteps
	projectConfig.Fuzzing.PruneFrequency = 0
	projectConfig.Fuzzing.CorpusDirectory = opts.CorpusDir
	projectConfig.Fuzzing.CoverageFormats = []string{}
	projectConfig.Fuzzing.TargetContracts = []string{fx.Contract}
	projectConfig.Fuzzing.SenderAddresses = []string{actor.Hex()}
	projectConfig.Fuzzing.DeployerAddress = deployer.Hex()
	projectConfig.Fuzzing.MaxBlockNumberDelay = 0
	projectConfig.Fuzzing.MaxBlockTimestampDelay = 0
	projectConfig.Fuzzing.TestChainConfig.SkipAccountChecks = false
	projectConfig.Fuzzing.Testing.TestViewMethods = false
	projectConfig.Fuzzing.Testing.TestAllContracts = false
	projectConfig.Fuzzing.Testing.StopOnNoTests = false
	projectConfig.Fuzzing.Testing.AssertionTesting.Enabled = false
	projectConfig.Fuzzing.Testing.PropertyTesting.Enabled = false
	projectConfig.Fuzzing.Testing.OptimizationTesting.Enabled = false
	projectConfig.Slither.UseSlither = false
	projectConfig.Logging.NoColor = true
	projectConfig.Logging.Level = zerolog.WarnLevel
	compileConfig := platforms.NewCryticCompilationConfig(fx.Project)
	compileConfig.ExportDirectory = strings.TrimSuffix(opts.Output, filepath.Ext(opts.Output)) + ".crytic-export"
	compileConfig.Args = []string{"--compile-force-framework", "foundry"}
	if err := projectConfig.Compilation.SetPlatformConfig(compileConfig); err != nil {
		return err
	}
	configPath := strings.TrimSuffix(opts.Output, filepath.Ext(opts.Output)) + ".medusa-config.json"
	if err := writeJSON(configPath, projectConfig); err != nil {
		return err
	}
	f, err := fuzzing.NewFuzzer(*projectConfig)
	if err != nil {
		return err
	}
	report := &runReport{SchemaVersion: 1, AdapterVersion: adapterVersion, MedusaVersion: medusaVersion, GoVersion: runtime.Version(), Fixture: fx.ID, Seed: opts.Seed, RNGStrategy: "single_worker_seeded_native_random_values_new_sequences_only_sorted_methods", ObserverEnabled: opts.Observe, WorkerCount: 1, MaxSteps: opts.MaxSteps, ImportedSequences: len(imports), CorpusDirectory: opts.CorpusDir, ConfigPath: configPath, Mode: "native_warmup", Status: "running", Sequences: []*sequenceRecord{}, Lineage: []lineageRecord{}}
	if len(imports) > 0 {
		report.Mode = "native_restart"
	}
	if opts.Campaign {
		report.SchemaVersion = 2
		report.Mode = "native_campaign"
		report.RNGStrategy = "single_worker_seeded_worker_rng_default_medusa_v1.5.1_generator_and_mutator_internal_choosers_uncontrolled"
		report.LineageEnabled = opts.RecordLineage
		if opts.RecordLineage && opts.LineageOutput == "" {
			opts.LineageOutput = strings.TrimSuffix(opts.Output, filepath.Ext(opts.Output)) + ".lineage.jsonl"
		}
		if opts.RecordLineage {
			report.LineagePath = opts.LineageOutput
		}
	}
	report.Deployment = map[string]any{"actor": actor.Hex(), "deployer": deployer.Hex(), "target": targetAddress.Hex(), "contract": fx.Contract, "constructor_arguments": []any{}}
	var found bool
	for _, def := range f.ContractDefinitions() {
		sort.Slice(def.AssertionTestMethods, func(i, j int) bool { return def.AssertionTestMethods[i].Sig < def.AssertionTestMethods[j].Sig })
		if def.Name() != fx.Contract {
			continue
		}
		found = true
		compiled := def.CompiledContract()
		if !bytes.Equal(compiled.InitBytecode, fx.Init) || !bytes.Equal(compiled.RuntimeBytecode, fx.Runtime) {
			return fmt.Errorf("actual Medusa bytecode differs from prebuilt Forge target")
		}
		if len(compiled.Abi.Methods) != len(fx.ABI.Methods) {
			return fmt.Errorf("actual Medusa ABI differs from Forge target")
		}
		if !reflect.DeepEqual(compiled.Abi, fx.ABI) {
			return fmt.Errorf("actual parsed Medusa ABI differs from parsed Forge ABI")
		}
		for name, method := range fx.ABI.Methods {
			other, ok := compiled.Abi.Methods[name]
			if !ok || other.Sig != method.Sig || other.StateMutability != method.StateMutability || fmt.Sprint(other.Outputs) != fmt.Sprint(method.Outputs) {
				return fmt.Errorf("actual Medusa ABI method differs: %s", name)
			}
		}
		sourceSHA, err := fileSHA(fx.SourcePath)
		if err != nil {
			return err
		}
		artifactSHA, err := fileSHA(fx.ArtifactPath)
		if err != nil {
			return err
		}
		foundrySHA, err := fileSHA(filepath.Join(fx.Project, "foundry.toml"))
		if err != nil {
			return err
		}
		var compact bytes.Buffer
		if err := json.Compact(&compact, fx.ArtifactABI); err != nil {
			return err
		}
		report.Build = map[string]any{"hash_algorithm": "sha256", "source_path": fx.SourcePath, "source_sha256": sourceSHA, "artifact_path": fx.ArtifactPath, "artifact_sha256": artifactSHA, "foundry_config_sha256": foundrySHA, "abi_sha256": sha256Hex(compact.Bytes()), "init_bytecode_sha256": sha256Hex(compiled.InitBytecode), "runtime_bytecode_sha256": sha256Hex(compiled.RuntimeBytecode), "medusa_build_matches_forge": true, "crytic_export_directory": compileConfig.ExportDirectory}
	}
	if !found {
		return fmt.Errorf("Medusa compilation missing fixture contract")
	}
	defaultGenerator := f.Hooks.NewCallSequenceGeneratorConfigFunc
	f.Hooks.NewCallSequenceGeneratorConfigFunc = func(fuzzer *fuzzing.Fuzzer, values *valuegeneration.ValueSet, rng *rand.Rand) (*fuzzing.CallSequenceGeneratorConfig, error) {
		rng.Seed(opts.Seed)
		cfg, err := defaultGenerator(fuzzer, values, rng)
		if err != nil {
			return nil, err
		}
		if opts.Campaign {
			report.GeneratorConfig = map[string]any{
				"new_sequence_probability":                      cfg.NewSequenceProbability,
				"random_unmodified_corpus_head_weight":          cfg.RandomUnmodifiedCorpusHeadWeight,
				"random_unmodified_corpus_tail_weight":          cfg.RandomUnmodifiedCorpusTailWeight,
				"random_unmodified_splice_at_random_weight":     cfg.RandomUnmodifiedSpliceAtRandomWeight,
				"random_unmodified_interleave_at_random_weight": cfg.RandomUnmodifiedInterleaveAtRandomWeight,
				"random_mutated_corpus_head_weight":             cfg.RandomMutatedCorpusHeadWeight,
				"random_mutated_corpus_tail_weight":             cfg.RandomMutatedCorpusTailWeight,
				"random_mutated_splice_at_random_weight":        cfg.RandomMutatedSpliceAtRandomWeight,
				"random_mutated_interleave_at_random_weight":    cfg.RandomMutatedInterleaveAtRandomWeight,
				"value_generator_type":                          fmt.Sprintf("%T", cfg.ValueGenerator),
				"value_mutator_type":                            fmt.Sprintf("%T", cfg.ValueMutator),
				"recording_patch":                               "medusa-v1.5.1-lineage.patch",
				"recording_rng_calls":                           0,
				"lineage_output_enabled":                        opts.RecordLineage,
			}
			return cfg, nil
		}
		// Medusa's corpus choosers own independent clock-seeded RNGs. Stage 1
		// never invokes them; this is an integration mode, not a stock baseline.
		cfg.NewSequenceProbability = 1
		nativeRandom := valuegeneration.NewRandomValueGenerator(&valuegeneration.RandomValueGeneratorConfig{}, rng)
		cfg.ValueGenerator, cfg.ValueMutator = nativeRandom, nativeRandom
		return cfg, nil
	}
	var timedOut atomic.Bool
	var current []stepRecord
	var currentRecords []*sequenceRecord
	knownIdentities := make(map[string]string, len(imports)+opts.Tests)
	importedHashes := make(map[string]bool, len(imports))
	for _, imported := range imports {
		knownIdentities[imported.Hash] = imported.Identity
		importedHashes[imported.Hash] = true
	}
	cumulativeCoverage := coverage.NewCoverageMaps()
	markers := coverageMarkers(fx.Runtime)
	var sequenceIndex int
	var fuzzStarted time.Time
	f.Events.WorkerCreated.Subscribe(func(event fuzzing.FuzzerWorkerCreatedEvent) error {
		event.Worker.Events.FuzzerWorkerChainSetup.Subscribe(func(setup fuzzing.FuzzerWorkerChainSetupEvent) error {
			if def := setup.Worker.DeployedContract(targetAddress); def == nil || def.Name() != fx.Contract {
				return fmt.Errorf("actual deployment does not match fixed address")
			}
			if !bytes.Equal(setup.Chain.State().GetCode(targetAddress), fx.Runtime) {
				return fmt.Errorf("actual deployed runtime differs from artifact")
			}
			// Native corpus processing removes per-transaction coverage before
			// the test hook. Copy only its counts at the earlier capture event.
			setup.Chain.AddTracer(&chain.TestChainTracer{
				Tracer: &tracers.Tracer{Hooks: &tracing.Hooks{}},
				CaptureTxEndSetAdditionalResults: func(result *chainTypes.MessageResults) {
					if cm := coverage.GetCoverageTracerResults(result); cm != nil {
						result.AdditionalResults["seedbridge.coverage_branches"] = cm.BranchesHit()
						if _, err := cumulativeCoverage.Update(cm); err != nil {
							result.AdditionalResults["seedbridge.coverage_error"] = err.Error()
							return
						}
						result.AdditionalResults["seedbridge.cumulative_coverage_branches"] = cumulativeCoverage.BranchesHit()
						digest, err := coverageDigest(cm, fx.Runtime, markers)
						if err != nil {
							result.AdditionalResults["seedbridge.coverage_error"] = err.Error()
							return
						}
						result.AdditionalResults["seedbridge.coverage_digest"] = digest
						markerSet, markerHits, err := coverageMarkerSnapshot(cm, fx.Runtime, markers)
						if err != nil {
							result.AdditionalResults["seedbridge.coverage_error"] = err.Error()
							return
						}
						result.AdditionalResults["seedbridge.coverage_markers"] = markerSet
						result.AdditionalResults["seedbridge.coverage_marker_hits"] = markerHits
						digest, err = coverageDigest(cumulativeCoverage, fx.Runtime, markers)
						if err != nil {
							result.AdditionalResults["seedbridge.coverage_error"] = err.Error()
							return
						}
						result.AdditionalResults["seedbridge.cumulative_coverage_digest"] = digest
						markerSet, markerHits, err = coverageMarkerSnapshot(cumulativeCoverage, fx.Runtime, markers)
						if err != nil {
							result.AdditionalResults["seedbridge.coverage_error"] = err.Error()
							return
						}
						result.AdditionalResults["seedbridge.cumulative_coverage_markers"] = markerSet
						result.AdditionalResults["seedbridge.cumulative_coverage_marker_hits"] = markerHits
					}
				},
			}, true, false)
			return nil
		})
		event.Worker.Events.CallSequenceTesting.Subscribe(func(_ fuzzing.FuzzerWorkerCallSequenceTestingEvent) error {
			current, currentRecords = nil, nil
			sequenceIndex++
			return nil
		})
		event.Worker.Events.CallSequenceTested.Subscribe(func(event fuzzing.FuzzerWorkerCallSequenceTestedEvent) error {
			report.CompletedSequences++
			if len(currentRecords) == 0 {
				return fmt.Errorf("native sequence completed without executed calls")
			}
			last := currentRecords[len(currentRecords)-1]
			last.Complete = true
			if opts.Campaign && opts.RecordLineage {
				// Medusa may admit an intermediate prefix when it adds coverage.
				// Retain every executed prefix identity so a later native parent
				// selection can be resolved without guessing from a full sequence.
				for _, executed := range currentRecords {
					prefixIdentity, err := stepSequenceIdentity(executed.Steps)
					if err != nil {
						return err
					}
					knownIdentities[executed.MedusaHash] = prefixIdentity
				}
				generation := event.Worker.CallSequenceGeneration()
				identity, err := stepSequenceIdentity(last.Steps)
				if err != nil {
					return err
				}
				lineage := lineageRecord{
					GenerationID: generation.GenerationID, SequenceIndex: sequenceIndex,
					Kind: generation.Kind, Strategy: generation.Strategy,
					ParentHashes: append([]string(nil), generation.ParentHashes...),
					OutputHash:   last.MedusaHash, OutputIdentity: identity, Executed: true,
					ParentsResolved:  len(generation.ParentHashes) > 0,
					CoverageBranches: last.Steps[len(last.Steps)-1].CumulativeCoverageBranches,
					CoverageDigest:   last.Steps[len(last.Steps)-1].CumulativeCoverageDigest,
					StateDigest:      last.Steps[len(last.Steps)-1].StateDigest,
					CompletedOffset:  time.Since(fuzzStarted).Seconds(),
				}
				lineage.ExecutionStatuses = make([]string, len(last.Steps))
				lineage.DifferentChild = generation.Kind == "mutation" && len(generation.ParentHashes) > 0
				for index, step := range last.Steps {
					lineage.ExecutionStatuses[index] = step.Status
					if step.Goal != nil && *step.Goal {
						lineage.GoalReached = true
					}
				}
				for _, parentHash := range generation.ParentHashes {
					parentIdentity, ok := knownIdentities[parentHash]
					if !ok {
						lineage.ParentsResolved = false
						lineage.DifferentChild = false
						continue
					}
					lineage.ParentIdentities = append(lineage.ParentIdentities, parentIdentity)
					if parentIdentity == identity {
						lineage.DifferentChild = false
					}
					if importedHashes[parentHash] {
						lineage.ImportedParent = true
					}
				}
				knownIdentities[last.MedusaHash] = identity
				report.Lineage = append(report.Lineage, lineage)
				switch generation.Kind {
				case "startup_replay":
					report.StartupReplays++
				case "mutation":
					report.MutationSequences++
				case "new_sequence":
					report.NewSequences++
				default:
					return fmt.Errorf("recording patch returned unknown generation kind %q", generation.Kind)
				}
			}
			if sequenceIndex <= len(imports) {
				var matched *importedSequence
				for i := range imports {
					if imports[i].Hash == last.MedusaHash && imports[i].Length == len(last.Steps) {
						matched = &imports[i]
						break
					}
				}
				if matched == nil {
					return fmt.Errorf("native startup sequence differs from imported input")
				}
				last.SourceNativePath = matched.Path
				last.Replayed = true
				if !timedOut.Load() {
					// At v1.5.1 this completion event is downstream of the native
					// admission call. All test providers are disabled, our hook returns
					// no shrink requests, and no cancellation occurred before this point.
					last.Admitted = true
					last.AdmissionStatus = "admitted_for_mutation"
					last.AdmissionEvidence = map[string]any{"kind": "medusa_v1.5.1_post_sequence_event", "event": "FuzzerWorker.CallSequenceTested", "native_input_hash_matched": true, "full_sequence_executed": true, "shrink_requests": 0, "cancellation_before_event": false, "source": "https://github.com/crytic/medusa/blob/v1.5.1/fuzzing/fuzzer_worker.go", "limitation": "source-bound control-flow evidence; no private chooser introspection"}
				}
			}
			if report.CompletedSequences >= opts.Tests {
				f.Stop()
			}
			return nil
		})
		return nil
	})
	f.Hooks.CallSequenceTestFuncs = append(f.Hooks.CallSequenceTestFuncs, func(worker *fuzzing.FuzzerWorker, seq calls.CallSequence) ([]fuzzing.ShrinkCallSequenceRequest, error) {
		element := seq[len(seq)-1]
		step, err := observeStep(fx, worker.Chain(), element, len(seq)-1, opts.Observe, cumulativeCoverage)
		if err != nil {
			return nil, err
		}
		current = append(current, step)
		path := filepath.Join(nativeDir, fmt.Sprintf("sequence-%05d-prefix-%d.json", sequenceIndex, len(seq)))
		digest, err := writeSequence(path, seq)
		if err != nil {
			return nil, err
		}
		hash, err := seq.Hash()
		if err != nil {
			return nil, err
		}
		origin := "native_generated_prefix"
		if sequenceIndex <= len(imports) {
			origin = "native_imported_prefix"
		}
		record := &sequenceRecord{SequenceIndex: sequenceIndex, Origin: origin, NativePath: path, NativeDigest: digest, MedusaHash: hash.Hex(), Steps: append([]stepRecord(nil), current...), AdmissionStatus: "not_checked"}
		currentRecords = append(currentRecords, record)
		report.Sequences = append(report.Sequences, record)
		return nil, nil
	})
	started := time.Now()
	fuzzStarted = started
	timer := time.AfterFunc(opts.Timeout, func() { timedOut.Store(true); f.Stop() })
	err = f.Start()
	timer.Stop()
	report.ElapsedSeconds = time.Since(started).Seconds()
	if opts.Campaign {
		startupElapsed := 0.0
		for _, event := range report.Lineage {
			if event.Kind == "startup_replay" && event.CompletedOffset > startupElapsed {
				startupElapsed = event.CompletedOffset
			}
		}
		totalElapsed := time.Since(runStarted).Seconds()
		report.NativeTiming = map[string]float64{
			"setup_before_fuzz": totalElapsed - report.ElapsedSeconds,
			"startup_replay":    startupElapsed,
			"continuation":      max(0, report.ElapsedSeconds-startupElapsed),
			"fuzz_total":        report.ElapsedSeconds,
			"adapter_total":     totalElapsed,
		}
	}
	report.CoverageBranches = cumulativeCoverage.BranchesHit()
	report.CoverageDigest, _ = coverageDigest(cumulativeCoverage, fx.Runtime, markers)
	report.CoverageMarkers, report.CoverageMarkerHits, _ = coverageMarkerSnapshot(cumulativeCoverage, fx.Runtime, markers)
	report.TimedOut = timedOut.Load()
	report.Status, report.Error = classifyRunOutcome(err, report.TimedOut)
	if opts.Campaign && opts.RecordLineage {
		if writeErr := writeJSONLines(opts.LineageOutput, report.Lineage); writeErr != nil {
			return writeErr
		}
	}
	if writeErr := writeJSON(opts.Output, report); writeErr != nil {
		return writeErr
	}
	if err != nil {
		return err
	}
	if report.TimedOut {
		return fmt.Errorf("fuzzing timeout; partial evidence saved to %s", opts.Output)
	}
	if report.CompletedSequences != opts.Tests {
		return fmt.Errorf("completed sequence count differs from requested count")
	}
	return nil
}

func classifyRunOutcome(runErr error, timedOut bool) (string, string) {
	if runErr != nil {
		return "tool_error", runErr.Error()
	}
	if timedOut {
		return "timeout", ""
	}
	return "complete", ""
}

func observeStep(fx *fixture, testChain *chain.TestChain, element *calls.CallSequenceElement, index int, enabled bool, cumulative *coverage.CoverageMaps) (stepRecord, error) {
	msg := element.Call
	method, err := fx.ABI.MethodById(msg.Data)
	if err != nil || !fx.Allowed[method.Sig] {
		return stepRecord{}, fmt.Errorf("native generator called unsupported fixture method")
	}
	decoded, err := method.Inputs.Unpack(msg.Data[4:])
	if err != nil {
		return stepRecord{}, err
	}
	arguments := make([]string, len(decoded))
	for i, value := range decoded {
		arguments[i] = fmt.Sprint(value)
	}
	result := element.ChainReference.MessageResults()
	step := stepRecord{Index: index, From: msg.From.Hex(), To: msg.To.Hex(), Nonce: msg.Nonce, Value: msg.Value.String(), Calldata: "0x" + hex.EncodeToString(msg.Data), Signature: method.Sig, Arguments: arguments, Status: "success", Success: !result.ExecutionResult.Failed(), BlockNumber: element.ChainReference.BlockNumber, BlockTimestamp: element.ChainReference.BlockTimestamp, GasUsed: result.Receipt.GasUsed, ReturnData: "0x" + hex.EncodeToString(result.ExecutionResult.ReturnData)}
	if !step.Success {
		step.Status = "revert"
	}
	step.CoverageBranches, _ = result.AdditionalResults["seedbridge.coverage_branches"].(uint64)
	step.CumulativeCoverageBranches = cumulative.BranchesHit()
	if message, ok := result.AdditionalResults["seedbridge.coverage_error"].(string); ok {
		return step, fmt.Errorf("coverage observer: %s", message)
	}
	step.CoverageDigest, _ = result.AdditionalResults["seedbridge.coverage_digest"].(string)
	step.CumulativeCoverageDigest, _ = result.AdditionalResults["seedbridge.cumulative_coverage_digest"].(string)
	step.CoverageMarkers, _ = result.AdditionalResults["seedbridge.coverage_markers"].([]string)
	step.CumulativeCoverageMarkers, _ = result.AdditionalResults["seedbridge.cumulative_coverage_markers"].([]string)
	step.CoverageMarkerHits, _ = result.AdditionalResults["seedbridge.coverage_marker_hits"].(map[string]uint64)
	step.CumulativeCoverageHits, _ = result.AdditionalResults["seedbridge.cumulative_coverage_marker_hits"].(map[string]uint64)
	if step.CoverageDigest == "" {
		return step, fmt.Errorf("native transaction coverage was unavailable")
	}
	step.StateRootBeforeObserver = testChain.State().IntermediateRoot(false).Hex()
	if enabled {
		observation, raw, err := readView(testChain, fx, "observe")
		if err != nil {
			return step, err
		}
		if len(observation) != 4 {
			return step, fmt.Errorf("observe must return four values")
		}
		goal, ok := observation[3].(bool)
		if !ok {
			return step, fmt.Errorf("observe goal must be bool")
		}
		step.Observe = []any{fmt.Sprint(observation[0]), fmt.Sprint(observation[1]), fmt.Sprint(observation[2]), goal}
		step.Goal, step.StateDigest = &goal, sha256Hex(raw)
		invariant, _, err := readView(testChain, fx, "invariantHolds")
		if err != nil {
			return step, err
		}
		if len(invariant) != 1 {
			return step, fmt.Errorf("invariantHolds must return one bool")
		}
		holds, ok := invariant[0].(bool)
		if !ok {
			return step, fmt.Errorf("invariantHolds must return bool")
		}
		step.InvariantHolds = &holds
	}
	step.StateRootAfterObserver = testChain.State().IntermediateRoot(false).Hex()
	step.ObserverStateUnchanged = step.StateRootBeforeObserver == step.StateRootAfterObserver
	if !step.ObserverStateUnchanged {
		return step, fmt.Errorf("observer changed persistent state")
	}
	return step, nil
}

func readView(testChain *chain.TestChain, fx *fixture, name string) ([]any, []byte, error) {
	data, err := fx.ABI.Pack(name)
	if err != nil {
		return nil, nil, err
	}
	msg := calls.NewCallMessage(actor, &targetAddress, 0, big.NewInt(0), 1000000, big.NewInt(0), big.NewInt(0), big.NewInt(0), data)
	msg.SkipNonceChecks = true
	result, err := testChain.CallContract(msg.ToCoreMessage(), nil)
	if err != nil {
		return nil, nil, err
	}
	if result == nil || result.Failed() {
		return nil, nil, fmt.Errorf("fixture getter %s failed", name)
	}
	values, err := fx.ABI.Unpack(name, result.ReturnData)
	return values, result.ReturnData, err
}
