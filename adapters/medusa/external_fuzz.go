package main

import (
	"os"

	compilationTypes "github.com/crytic/medusa/compilation/types"
)

func externalFuzzerCompilation(fx *fixture) (compilationTypes.Compilation, error) {
	compilation := compilationTypes.NewCompilation()
	source, err := os.ReadFile(fx.SourcePath)
	if err != nil {
		return *compilation, err
	}
	compilation.SourceCode[fx.SourcePath] = source
	compilation.SourceIdToPath[0] = fx.SourcePath
	compilation.SourcePathToArtifact[fx.SourcePath] = compilationTypes.SourceArtifact{
		Ast: map[string]any{},
		Contracts: map[string]compilationTypes.CompiledContract{
			fx.Contract: {
				Abi:             fx.ABI,
				InitBytecode:    append([]byte(nil), fx.Init...),
				RuntimeBytecode: append([]byte(nil), fx.Runtime...),
				Kind:            compilationTypes.ContractKindContract,
			},
		},
		SourceUnitId: 0,
	}
	return *compilation, nil
}
