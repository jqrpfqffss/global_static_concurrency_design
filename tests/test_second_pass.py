"""Regression tests for second-pass corrections: inactive branches,
supplemental isolation, per-file coverage, and global/static-only inventory.

Tests that need inactive branch / supplemental / file coverage use the
full `run()` pipeline, not direct Extractor calls.
"""
import json
from pathlib import Path
import tempfile
import unittest

from ecra.analysis import analyze, merge
from ecra.compilation import prepare
from ecra.config import load_config
from ecra.extract import Extractor
from ecra.html_report import write_html
from ecra.supplemental import (merge_supplemental_variables, _track_conditionals,
                               _find_inactive_branches)
from ecra.scope import AuditScope


ROOT = Path(__file__).resolve().parents[1]


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ecra 2nd ")
        self.root = Path(self.tmp.name).resolve()
        self.addCleanup(self.tmp.cleanup)
        self.original_cwd = Path.cwd()
        self.addCleanup(lambda: __import__("os").chdir(self.original_cwd))
        (self.root / ".ecra").mkdir()

    def setup_run(self, sources, contexts=None, **analysis):
        entries = []
        for name, text in sources.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            if name.endswith((".c", ".cpp")):
                entries.append(dict(directory=str(self.root), file=name,
                                    arguments=["arm-none-eabi-gcc", "-mcpu=cortex-m7", "-mthumb", "-c", name]))
        (self.root / "compile_commands.json").write_text(json.dumps(entries), encoding="utf-8")
        cfg = dict(version=1, analysis=dict(compile_database="compile_commands.json", **analysis),
                   contexts=contexts or [dict(id="isr", kind="ISR", functions=["ISR"]),
                                        dict(id="task", kind="TASK", functions=["Task"])],
                   review=dict(enabled=False))
        (self.root / ".ecra/semantics.yaml").write_text(json.dumps(cfg), encoding="utf-8")
        from ecra.cli import run
        run(self.root, no_review=True)
        facts = json.loads((self.root / ".ecra/facts.json").read_text(encoding="utf-8"))
        report = json.loads((self.root / ".ecra/reports/global_static_concurrency.json").read_text(encoding="utf-8"))
        return facts, report

    def project(self, sources, contexts=None, **analysis):
        entries = []
        for name, text in sources.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            if name.endswith((".c", ".cpp")):
                entries.append(dict(directory=str(self.root), file=name,
                                    arguments=["arm-none-eabi-gcc", "-mcpu=cortex-m7", "-mthumb", "-c", name]))
        (self.root / "compile_commands.json").write_text(json.dumps(entries), encoding="utf-8")
        cfg = dict(version=1, analysis=dict(compile_database="compile_commands.json", **analysis),
                   contexts=contexts or [dict(id="isr", kind="ISR", functions=["ISR"]),
                                        dict(id="task", kind="TASK", functions=["Task"])],
                   review=dict(enabled=False))
        (self.root / ".ecra/semantics.yaml").write_text(json.dumps(cfg), encoding="utf-8")
        return load_config(self.root)[0]

    def extract(self, cfg):
        units, audit = prepare(self.root, cfg)
        parts = [Extractor(dict(root=str(self.root), unit=u, config=cfg)).run() for u in units]
        for part in parts:
            self.assertEqual(part["parse_status"], "PARSED", part.get("diagnostics"))
        facts = merge(parts)
        coverage = dict(translation_units_failed=0, **audit)
        report = analyze(facts, cfg, coverage)
        return facts, report


class TestInactiveBranches(Fixture):
    def test_if_zero_single_line(self):
        """A single-line #if 0 branch must be inventoried."""
        facts, report = self.setup_run({"a.c": "int g;\n#if 0\nint hidden = 42;\n#endif\nvoid ISR(void){g++;} void Task(void){g++;}"})
        hidden = [v for v in facts["variables"] if v["name"] == "hidden"]
        self.assertTrue(hidden, "inactive branch variable 'hidden' not found in inventory")
        self.assertEqual(hidden[0].get("coverage_source"), "inactive_branch")
        self.assertEqual(hidden[0].get("definition_file"), "a.c")
        self.assertEqual(hidden[0].get("definition_line"), 3)

    def test_else_branch(self):
        """An inactive #else branch must be inventoried."""
        facts, report = self.setup_run({"a.c": "#define FEATURE 1\n#if FEATURE\nint active_var;\n#else\nint inactive_var;\n#endif\nvoid ISR(void){active_var++;} void Task(void){active_var++;}"})
        inactive = [v for v in facts["variables"] if v["name"] == "inactive_var"]
        self.assertTrue(inactive, "inactive #else branch variable not found")
        self.assertEqual(inactive[0].get("coverage_source"), "inactive_branch")
        self.assertEqual(inactive[0].get("definition_file"), "a.c")
        self.assertEqual(inactive[0].get("definition_line"), 5)

    def test_if_value_zero(self):
        """#if MACRO where MACRO is defined as 0 must have inactive #if branch."""
        facts, report = self.setup_run({"a.c": "#define VALUE 0\n#if VALUE\nint inactive;\n#else\nint active;\n#endif\nvoid ISR(void){active++;} void Task(void){active++;}"})
        inactive = [v for v in facts["variables"] if v["name"] == "inactive"]
        self.assertTrue(inactive, "inactive #if VALUE branch variable not found")
        self.assertEqual(inactive[0].get("coverage_source"), "inactive_branch")

    def test_nested_branches(self):
        """Nested conditional branches must be handled correctly."""
        facts, report = self.setup_run({"a.c": "int g;\n#if 0\nint outer_inactive;\n#if 1\nint inner_active_in_inactive;\n#endif\n#endif\nvoid ISR(void){g++;} void Task(void){g++;}"})
        outer = [v for v in facts["variables"] if v["name"] == "outer_inactive"]
        self.assertTrue(outer, "outer inactive branch variable not found")
        self.assertEqual(outer[0].get("coverage_source"), "inactive_branch")

    def test_typedef_outside_branch(self):
        """An inactive local using typedefs defined outside the branch must parse."""
        facts, report = self.setup_run({"a.c": "int g;\ntypedef int my_int;\n#if 0\nmy_int inactive_typed;\n#endif\nvoid ISR(void){g++;} void Task(void){g++;}"})
        typed = [v for v in facts["variables"] if v["name"] == "inactive_typed"]
        self.assertTrue(typed, "inactive branch variable using external typedef not found")
        self.assertEqual(typed[0].get("coverage_source"), "inactive_branch")

    def test_original_line_in_html(self):
        """HTML inventory must show original file and line, not worker paths."""
        facts, report = self.setup_run({"a.c": "int g;\n#if 0\nint hidden_var = 99;\n#endif\nvoid ISR(void){g++;} void Task(void){g++;}"})
        html = (self.root / ".ecra/index.html").read_text(encoding="utf-8")
        self.assertIn("hidden_var", html)
        self.assertIn("a.c", html)
        self.assertNotIn("INACT_", html)

    def test_unlisted_source_inactive_branch(self):
        """An inactive branch in an unlisted source file must be inventoried."""
        (self.root / "a.c").write_text("int g; void ISR(void){g++;} void Task(void){g++;}", encoding="utf-8")
        (self.root / "extra.c").write_text("#if 0\nint extra_hidden;\n#endif\nvoid Extra(void){}", encoding="utf-8")
        (self.root / "compile_commands.json").write_text(json.dumps([
            dict(directory=str(self.root), file="a.c",
                 arguments=["arm-none-eabi-gcc", "-mcpu=cortex-m7", "-mthumb", "-c", "a.c"])
        ]), encoding="utf-8")
        cfg = dict(version=1, analysis=dict(compile_database="compile_commands.json"),
                   contexts=[dict(id="isr", kind="ISR", functions=["ISR"]),
                             dict(id="task", kind="TASK", functions=["Task"])],
                   review=dict(enabled=False))
        (self.root / ".ecra/semantics.yaml").write_text(json.dumps(cfg), encoding="utf-8")
        from ecra.cli import run
        run(self.root, no_review=True)
        facts = json.loads((self.root / ".ecra/facts.json").read_text(encoding="utf-8"))
        hidden = [v for v in facts["variables"] if v["name"] == "extra_hidden"]
        self.assertTrue(hidden, "inactive branch in unlisted source not found")
        self.assertEqual(hidden[0].get("coverage_source"), "inactive_branch")
        self.assertEqual(hidden[0].get("definition_file"), "extra.c")

    def test_header_inactive_globals(self):
        """Inactive globals in a header file must be inventoried."""
        (self.root / "a.c").write_text('#include "config.h"\nint g; void ISR(void){g++;} void Task(void){g++;}', encoding="utf-8")
        (self.root / "config.h").write_text("#if 0\nint inactive_header_global;\n#endif\n", encoding="utf-8")
        (self.root / "compile_commands.json").write_text(json.dumps([
            dict(directory=str(self.root), file="a.c",
                 arguments=["arm-none-eabi-gcc", "-mcpu=cortex-m7", "-mthumb", "-I.", "-c", "a.c"])
        ]), encoding="utf-8")
        cfg = dict(version=1, analysis=dict(compile_database="compile_commands.json"),
                   contexts=[dict(id="isr", kind="ISR", functions=["ISR"]),
                             dict(id="task", kind="TASK", functions=["Task"])],
                   review=dict(enabled=False))
        (self.root / ".ecra/semantics.yaml").write_text(json.dumps(cfg), encoding="utf-8")
        from ecra.cli import run
        run(self.root, no_review=True)
        facts = json.loads((self.root / ".ecra/facts.json").read_text(encoding="utf-8"))
        hidden = [v for v in facts["variables"] if v["name"] == "inactive_header_global"]
        self.assertTrue(hidden, "inactive header global not found")
        # Check that the declaration location is in config.h (may be in declarations, not definition_file)
        decl_files = [d.get("file") for d in hidden[0].get("declarations", [])]
        self.assertIn("config.h", decl_files, "inactive header variable must have declaration in config.h")


class TestSupplementalIsolation(Fixture):
    def test_supplemental_does_not_invent_irq_context(self):
        """An unlisted file with an IRQ writing a compiled shared extern must not
        give the compiled variable any inactive IRQ context or write."""
        (self.root / "a.c").write_text("int g; void ISR(void){g++;} void Task(void){g++;}", encoding="utf-8")
        (self.root / "extra.c").write_text("extern int g;\nvoid ExtraIRQHandler(void){g=99;}", encoding="utf-8")
        (self.root / "compile_commands.json").write_text(json.dumps([
            dict(directory=str(self.root), file="a.c",
                 arguments=["arm-none-eabi-gcc", "-mcpu=cortex-m7", "-mthumb", "-c", "a.c"])
        ]), encoding="utf-8")
        cfg = dict(version=1, analysis=dict(compile_database="compile_commands.json"),
                   contexts=[dict(id="isr", kind="ISR", functions=["ISR"]),
                             dict(id="task", kind="TASK", functions=["Task"])],
                   review=dict(enabled=False))
        (self.root / ".ecra/semantics.yaml").write_text(json.dumps(cfg), encoding="utf-8")
        from ecra.cli import run
        run(self.root, no_review=True)
        facts = json.loads((self.root / ".ecra/facts.json").read_text(encoding="utf-8"))
        g = next(v for v in facts["variables"] if v["name"] == "g" and v.get("coverage_source", "compile_database") == "compile_database")
        self.assertNotIn("ExtraIRQHandler", str(g.get("writers", [])))
        self.assertNotIn("ExtraIRQHandler", str(g.get("contexts", [])))
        self.assertFalse(any(f["name"] == "ExtraIRQHandler" for f in facts["functions"]))

    def test_supplemental_does_not_replace_compiled_function(self):
        """A conflicting unbuilt external function must not replace compiled function."""
        (self.root / "a.c").write_text("int g; void ISR(void){g++;} void Task(void){g++;}", encoding="utf-8")
        (self.root / "extra.c").write_text("void ISR(void){/* different body */}", encoding="utf-8")
        (self.root / "compile_commands.json").write_text(json.dumps([
            dict(directory=str(self.root), file="a.c",
                 arguments=["arm-none-eabi-gcc", "-mcpu=cortex-m7", "-mthumb", "-c", "a.c"])
        ]), encoding="utf-8")
        cfg = dict(version=1, analysis=dict(compile_database="compile_commands.json"),
                   contexts=[dict(id="isr", kind="ISR", functions=["ISR"]),
                             dict(id="task", kind="TASK", functions=["Task"])],
                   review=dict(enabled=False))
        (self.root / ".ecra/semantics.yaml").write_text(json.dumps(cfg), encoding="utf-8")
        from ecra.cli import run
        run(self.root, no_review=True)
        facts = json.loads((self.root / ".ecra/facts.json").read_text(encoding="utf-8"))
        isrs = [f for f in facts["functions"] if f["name"] == "ISR"]
        self.assertEqual(len(isrs), 1)


class TestFieldDecl(Fixture):
    def test_struct_fields_are_excluded_from_inventory(self):
        """Struct/union fields are part of their container, not separate objects."""
        cfg = self.project({"a.c": """
            struct Packet { int seq; unsigned flag:1; char data[8]; };
            struct Packet pkt;
            void ISR(void){pkt.seq++;} void Task(void){pkt.seq++;}
        """})
        facts, _ = self.extract(cfg)
        fields = [v for v in facts["variables"] if v["kind"] == "FIELD"]
        self.assertEqual(fields, [])
        self.assertFalse(any(v["name"] in {"seq", "flag", "data"} for v in facts["variables"]))
        self.assertIn("pkt", {v["name"] for v in facts["variables"]})


class TestParameterIdentity(Fixture):
    def test_parameters_are_excluded_from_inventory(self):
        """Function parameters are not independent shared objects."""
        cfg = self.project({
            "h.h": "void Process(int count, char *buffer);",
            "a.c": '#include "h.h"\nint g;\nvoid Process(int count, char *buffer){g += count;}\nvoid ISR(void){g++;} void Task(void){Process(1, 0);}',
        })
        facts, _ = self.extract(cfg)
        counts = [v for v in facts["variables"] if v["name"] == "count"]
        self.assertEqual(counts, [])
        self.assertFalse(any(v["kind"] == "PARAMETER" for v in facts["variables"]))


class TestPerFileCoverage(Fixture):
    def test_file_coverage_in_report(self):
        """Coverage must include per-file table with counts and status."""
        facts, report = self.setup_run({
            "a.c": "int g; void ISR(void){g++;} void Task(void){g++;}",
            "b.c": "static int b_var; void Other(void){b_var++;}",
        })
        self.assertIn("file_coverage", report["coverage"])
        fc = report["coverage"]["file_coverage"]
        files = {row["file"]: row for row in fc}
        self.assertIn("a.c", files)
        self.assertIn("b.c", files)

    def test_zero_var_file_in_coverage(self):
        """A selected file with zero variables must still appear in coverage."""
        facts, report = self.setup_run({
            "a.c": "int g; void ISR(void){g++;} void Task(void){g++;}",
            "empty.c": "/* no variables */\nvoid Empty(void){}",
        })
        fc = report["coverage"]["file_coverage"]
        files = {row["file"]: row for row in fc}
        self.assertIn("empty.c", files)
        self.assertEqual(files["empty.c"]["variable_count"], 0)


class TestMergeSupplemental(Fixture):
    def test_same_sid_keeps_compiled_ownership(self):
        """Merging supplemental vars with same SID must not contaminate compiled ownership."""
        compiled_var = dict(symbol_id="c:@g", name="g", kind="GLOBAL", coverage_source="compile_database",
                            declarations=[dict(file="a.c", line=1)], definitions=[dict(file="a.c", line=1)],
                            definition_file="a.c", definition_line=1, translation_units=["a.c"],
                            is_const=False, is_volatile=False, is_array=False, is_pointer=False,
                            is_struct=False, is_bitfield_container=False, type="int",
                            size_bytes=4, alignment_bytes=4, scope="file", storage_class="NONE",
                            linkage="EXTERNAL", qualified_name="g", initializer="")
        supplemental_var = dict(symbol_id="c:@g", name="g", kind="GLOBAL", coverage_source="inactive_branch",
                                declarations=[dict(file="a.c", line=5)], definitions=[dict(file="a.c", line=5)],
                                definition_file="a.c", definition_line=5, translation_units=["a.c"],
                                is_const=False, is_volatile=False, is_array=False, is_pointer=False,
                                is_struct=False, is_bitfield_container=False, type="int",
                                size_bytes=4, alignment_bytes=4, scope="file", storage_class="NONE",
                                linkage="EXTERNAL", qualified_name="g", initializer="")
        facts = dict(variables=[compiled_var], functions=[], calls=[], contexts=[], unknowns=[],
                     accesses=[], snapshots=[], protection_events=[], registrations=[],
                     pointer_constraints=[], semantic_calls=[], indirect_accesses=[],
                     translation_units=[])
        merge_supplemental_variables(facts, [supplemental_var])
        self.assertEqual(len(facts["variables"]), 1)
        merged = facts["variables"][0]
        self.assertEqual(merged["coverage_source"], "compile_database")
        self.assertTrue(any(d.get("provenance") == "inactive_branch" for d in merged["declarations"]))

    def test_new_sid_added_as_supplemental(self):
        """A truly new supplemental variable should be added to inventory."""
        facts = dict(variables=[], functions=[], calls=[], contexts=[], unknowns=[],
                     accesses=[], snapshots=[], protection_events=[], registrations=[],
                     pointer_constraints=[], semantic_calls=[], indirect_accesses=[],
                     translation_units=[])
        new_var = dict(symbol_id="c:@extra", name="extra", kind="GLOBAL", coverage_source="supplemental",
                       declarations=[dict(file="extra.c", line=1)], definitions=[dict(file="extra.c", line=1)],
                       definition_file="extra.c", definition_line=1, translation_units=["extra.c"],
                       is_const=False, is_volatile=False, is_array=False, is_pointer=False,
                       is_struct=False, is_bitfield_container=False, type="int",
                       size_bytes=4, alignment_bytes=4, scope="file", storage_class="NONE",
                       linkage="EXTERNAL", qualified_name="extra", initializer="")
        merge_supplemental_variables(facts, [new_var])
        self.assertEqual(len(facts["variables"]), 1)
        self.assertEqual(facts["variables"][0]["coverage_source"], "supplemental")


class TestConditionalTracking(unittest.TestCase):
    def test_track_conditionals_basic(self):
        lines = ["#if 0", "int x;", "#endif", "int y;"]
        groups = _track_conditionals(lines)
        self.assertEqual(len(groups), 1)

    def test_track_conditionals_nested(self):
        lines = ["#if 1", "int x;", "#if 0", "int y;", "#endif", "#endif"]
        groups = _track_conditionals(lines)
        self.assertEqual(len(groups), 2)

    def test_find_inactive_single_line(self):
        groups = _track_conditionals(["#if 0", "int x;", "#endif"])
        inactive = _find_inactive_branches(groups, set())
        self.assertEqual(len(inactive), 1)


if __name__ == "__main__":
    unittest.main()
