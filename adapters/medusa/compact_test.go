package main

import (
	"compress/gzip"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestCompactWriterKeepsExplicitZeroEOFCounts(t *testing.T) {
	path := filepath.Join(t.TempDir(), "events.jsonl.gz")
	writer, err := newCompactEventWriter(path)
	if err != nil {
		t.Fatal(err)
	}
	metadata, err := writer.close()
	if err != nil {
		t.Fatal(err)
	}
	if metadata["schema_version"] != 2 || metadata["sequence_records"] != 0 || metadata["partial_records"] != 0 {
		t.Fatalf("unexpected metadata: %#v", metadata)
	}
	file, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	compressed, err := gzip.NewReader(file)
	if err != nil {
		t.Fatal(err)
	}
	defer compressed.Close()
	var event map[string]any
	if err := json.NewDecoder(compressed).Decode(&event); err != nil {
		t.Fatal(err)
	}
	if event["record_type"] != "eof" || event["sequence_count"] != float64(0) || event["partial_count"] != float64(0) {
		t.Fatalf("EOF did not retain explicit zero counts: %#v", event)
	}
}

func TestCompactPrefixReferencesIncludeEveryExecutedPrefix(t *testing.T) {
	records := []*sequenceRecord{
		{MedusaHash: "one", Steps: []stepRecord{{From: "from", To: "to", Value: "0", Calldata: "0x01"}}},
		{MedusaHash: "two", Steps: []stepRecord{{From: "from", To: "to", Value: "0", Calldata: "0x01"}, {From: "from", To: "to", Value: "0", Calldata: "0x02"}}},
	}
	refs, err := compactPrefixReferences(records)
	if err != nil {
		t.Fatal(err)
	}
	if len(refs) != 2 || refs[0].StepCount != 1 || refs[1].StepCount != 2 || refs[1].MedusaHash != "two" {
		t.Fatalf("unexpected prefix references: %#v", refs)
	}
}

func TestCompactWriterRecordsPartialSequence(t *testing.T) {
	path := filepath.Join(t.TempDir(), "partial.jsonl.gz")
	writer, err := newCompactEventWriter(path)
	if err != nil {
		t.Fatal(err)
	}
	sequence := &sequenceRecord{SequenceIndex: 1, MedusaHash: "partial", Steps: []stepRecord{{Status: "success"}}}
	refs := []compactPrefixReference{{MedusaHash: "partial", IdentityHash: "identity", StepCount: 1}}
	if err := writer.writePartial(sequence, refs, []byte("[]\n")); err != nil {
		t.Fatal(err)
	}
	metadata, err := writer.close()
	if err != nil {
		t.Fatal(err)
	}
	if metadata["sequence_records"] != 0 || metadata["partial_records"] != 1 {
		t.Fatalf("partial record counts differ: %#v", metadata)
	}
}

func TestCompactWriterReportsFlushFailure(t *testing.T) {
	writer, err := newCompactEventWriter(filepath.Join(t.TempDir(), "failure.jsonl.gz"))
	if err != nil {
		t.Fatal(err)
	}
	if err := writer.file.Close(); err != nil {
		t.Fatal(err)
	}
	if _, err := writer.close(); err == nil {
		t.Fatal("expected evidence flush failure")
	}
}
