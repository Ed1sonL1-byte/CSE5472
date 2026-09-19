package main

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"sort"

	"github.com/crytic/medusa/fuzzing/coverage"
)

// coverageMarkerSnapshot exports stable marker identities and hit counts for one runtime bytecode target.
// Marker identity excludes hit count so set union and difference remain independent of execution frequency.
func coverageMarkerSnapshot(maps *coverage.CoverageMaps, code []byte, markers []uint64) ([]string, map[string]uint64, error) {
	contract, err := maps.GetContractCoverageMap(code, false)
	if err != nil {
		return nil, nil, err
	}
	runtimeDigest := sha256Hex(code)
	identities := make([]string, 0, maps.BranchesHit())
	hits := make(map[string]uint64, maps.BranchesHit())
	for _, marker := range markers {
		count := contract.HitCount(marker)
		if count == 0 {
			continue
		}
		identity := fmt.Sprintf("%s:0x%016x", runtimeDigest, marker)
		identities = append(identities, identity)
		hits[identity] = count
	}
	if uint64(len(identities)) != maps.BranchesHit() {
		return nil, nil, fmt.Errorf("enumerated %d native markers but native map reports %d", len(identities), maps.BranchesHit())
	}
	return identities, hits, nil
}

// Enumerate possible v1.5.1 markers through bytecode PCs, then query the public
// HitCount API. No private map reflection or separate coverage engine is used.
// A count check below ensures that an omitted native marker fails the run.
func coverageMarkers(code []byte) []uint64 {
	pcs, jumps := []uint64{}, []uint64{}
	for pc := 0; pc < len(code); pc++ {
		op := code[pc]
		pcs = append(pcs, uint64(pc))
		if op == 0x56 || op == 0x57 {
			jumps = append(jumps, uint64(pc))
		}
		if op >= 0x60 && op <= 0x7f {
			pc += int(op - 0x5f)
		}
	}
	set := map[uint64]struct{}{}
	for _, pc := range pcs {
		set[uint64(coverage.ENTER_MARKER_XOR)<<32^pc] = struct{}{}
		set[pc<<32^uint64(coverage.RETURN_MARKER_XOR)] = struct{}{}
		set[pc<<32^uint64(coverage.REVERT_MARKER_XOR)] = struct{}{}
		for _, jump := range jumps {
			set[jump<<32^pc] = struct{}{}
		}
	}
	markers := make([]uint64, 0, len(set))
	for marker := range set {
		markers = append(markers, marker)
	}
	sort.Slice(markers, func(i, j int) bool { return markers[i] < markers[j] })
	return markers
}

// SHA256 of sorted big-endian (native marker uint64, hit count uint64) pairs.
func coverageDigest(maps *coverage.CoverageMaps, code []byte, markers []uint64) (string, error) {
	contract, err := maps.GetContractCoverageMap(code, false)
	if err != nil {
		return "", err
	}
	var encoded bytes.Buffer
	var found uint64
	for _, marker := range markers {
		count := contract.HitCount(marker)
		if count == 0 {
			continue
		}
		found++
		_ = binary.Write(&encoded, binary.BigEndian, marker)
		_ = binary.Write(&encoded, binary.BigEndian, count)
	}
	if found != maps.BranchesHit() {
		return "", fmt.Errorf("enumerated %d native markers but native map reports %d", found, maps.BranchesHit())
	}
	return sha256Hex(encoded.Bytes()), nil
}
