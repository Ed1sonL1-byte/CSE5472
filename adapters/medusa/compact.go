package main

import (
	"compress/gzip"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

type compactEvent struct {
	SchemaVersion int                      `json:"schema_version"`
	RecordType    string                   `json:"record_type"`
	Sequence      *sequenceRecord          `json:"sequence,omitempty"`
	Lineage       *lineageRecord           `json:"lineage,omitempty"`
	PrefixRefs    []compactPrefixReference `json:"prefix_references,omitempty"`
	NativePayload string                   `json:"native_payload_base64,omitempty"`
	SequenceCount int                      `json:"sequence_count"`
	PartialCount  int                      `json:"partial_count"`
}

type compactPrefixReference struct {
	MedusaHash   string `json:"medusa_hash"`
	IdentityHash string `json:"identity_hash"`
	StepCount    int    `json:"step_count"`
}

type compactEventWriter struct {
	path          string
	file          *os.File
	gzip          *gzip.Writer
	encoder       *json.Encoder
	sequenceCount int
	partialCount  int
	closed        bool
}

func newCompactEventWriter(path string) (*compactEventWriter, error) {
	if path == "" {
		return nil, fmt.Errorf("compact event output path is required")
	}
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return nil, err
	}
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0644)
	if err != nil {
		return nil, err
	}
	compressed := gzip.NewWriter(file)
	return &compactEventWriter{
		path: path, file: file, gzip: compressed, encoder: json.NewEncoder(compressed),
	}, nil
}

func (writer *compactEventWriter) writeSequence(sequence *sequenceRecord, lineage *lineageRecord, refs []compactPrefixReference, payload []byte) error {
	if writer.closed {
		return fmt.Errorf("compact event stream is already closed")
	}
	if err := writer.encoder.Encode(compactEvent{
		SchemaVersion: 2, RecordType: "sequence", Sequence: sequence,
		Lineage: lineage, PrefixRefs: refs, NativePayload: base64.StdEncoding.EncodeToString(payload),
	}); err != nil {
		return err
	}
	writer.sequenceCount++
	return nil
}

func compactPrefixReferences(records []*sequenceRecord) ([]compactPrefixReference, error) {
	refs := make([]compactPrefixReference, 0, len(records))
	for _, record := range records {
		identity, err := stepSequenceIdentity(record.Steps)
		if err != nil {
			return nil, err
		}
		refs = append(refs, compactPrefixReference{
			MedusaHash: record.MedusaHash, IdentityHash: identity, StepCount: len(record.Steps),
		})
	}
	return refs, nil
}

func (writer *compactEventWriter) writePartial(sequence *sequenceRecord, refs []compactPrefixReference, payload []byte) error {
	if writer.closed {
		return fmt.Errorf("compact event stream is already closed")
	}
	if err := writer.encoder.Encode(compactEvent{
		SchemaVersion: 2, RecordType: "partial", Sequence: sequence,
		PrefixRefs: refs, NativePayload: base64.StdEncoding.EncodeToString(payload),
	}); err != nil {
		return err
	}
	writer.partialCount++
	return nil
}

func (writer *compactEventWriter) close() (map[string]any, error) {
	if writer.closed {
		return nil, fmt.Errorf("compact event stream is already closed")
	}
	writer.closed = true
	if err := writer.encoder.Encode(compactEvent{
		SchemaVersion: 2, RecordType: "eof", SequenceCount: writer.sequenceCount,
		PartialCount: writer.partialCount,
	}); err != nil {
		_ = writer.gzip.Close()
		_ = writer.file.Close()
		return nil, err
	}
	if err := writer.gzip.Close(); err != nil {
		_ = writer.file.Close()
		return nil, err
	}
	if err := writer.file.Sync(); err != nil {
		_ = writer.file.Close()
		return nil, err
	}
	if err := writer.file.Close(); err != nil {
		return nil, err
	}
	info, err := os.Stat(writer.path)
	if err != nil {
		return nil, err
	}
	digest, err := fileSHA(writer.path)
	if err != nil {
		return nil, err
	}
	return map[string]any{
		"schema_version":   2,
		"path":             writer.path,
		"encoding":         "gzip-jsonl",
		"sequence_records": writer.sequenceCount,
		"partial_records":  writer.partialCount,
		"eof_record":       true,
		"compressed_bytes": info.Size(),
		"sha256":           digest,
	}, nil
}
