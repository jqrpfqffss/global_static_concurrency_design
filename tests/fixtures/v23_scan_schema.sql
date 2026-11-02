
CREATE TABLE nodes (
 id INTEGER PRIMARY KEY, hash TEXT UNIQUE, kind TEXT NOT NULL,
 value BLOB, length INTEGER NOT NULL CHECK(length>=0));
CREATE TABLE edges (
 parent INTEGER NOT NULL REFERENCES nodes(id), ordinal INTEGER NOT NULL,
 key TEXT, child INTEGER NOT NULL REFERENCES nodes(id),
 PRIMARY KEY(parent,ordinal));
CREATE INDEX edge_child ON edges(child);
CREATE TABLE roots (name TEXT PRIMARY KEY, node INTEGER NOT NULL REFERENCES nodes(id));
CREATE TABLE records (
 dataset TEXT NOT NULL, relation TEXT NOT NULL, ordinal INTEGER NOT NULL,
 node INTEGER NOT NULL REFERENCES nodes(id), symbol_id TEXT, function_id TEXT,
 source_id TEXT, target_id TEXT, PRIMARY KEY(dataset,relation,ordinal));
CREATE INDEX record_symbol ON records(dataset,relation,symbol_id,ordinal);
CREATE INDEX record_function ON records(dataset,relation,function_id,ordinal);
CREATE INDEX record_source ON records(dataset,relation,source_id,ordinal);
CREATE INDEX record_target ON records(dataset,relation,target_id,ordinal);
CREATE TABLE symbols (
 symbol_id TEXT PRIMARY KEY, ordinal INTEGER NOT NULL UNIQUE,
 node INTEGER NOT NULL REFERENCES nodes(id), name TEXT NOT NULL,
 static_classification TEXT NOT NULL, resource_kind TEXT NOT NULL,
 definition_file TEXT, definition_line INTEGER, analysis_coverage TEXT);
CREATE INDEX symbol_class ON symbols(static_classification,ordinal);
CREATE INDEX symbol_name ON symbols(name,ordinal);
CREATE TABLE projects (project_id TEXT PRIMARY KEY, node INTEGER REFERENCES nodes(id));
CREATE TABLE profiles (profile_id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(project_id));
CREATE TABLE scans (
 scan_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(project_id),
 profile_id TEXT REFERENCES profiles(profile_id), state TEXT NOT NULL,
 facts_hash TEXT NOT NULL, report_hash TEXT NOT NULL);
CREATE VIEW functions AS SELECT * FROM records WHERE dataset='facts' AND relation='functions';
CREATE VIEW accesses AS SELECT * FROM records WHERE dataset='facts' AND relation='accesses';
CREATE VIEW call_edges AS SELECT * FROM records WHERE dataset='facts' AND relation='calls';
CREATE VIEW protection_events AS SELECT * FROM records WHERE dataset='facts' AND relation='protection_events';
CREATE VIEW findings AS SELECT * FROM records WHERE dataset='report' AND relation='findings';
CREATE VIEW irq_priorities AS SELECT * FROM records WHERE dataset='facts' AND relation='irq_priority_events';
CREATE VIEW coverage_gaps AS SELECT * FROM records WHERE dataset='facts' AND relation='unknowns';
CREATE VIEW translation_units AS SELECT * FROM records WHERE dataset='facts' AND relation='translation_units';
