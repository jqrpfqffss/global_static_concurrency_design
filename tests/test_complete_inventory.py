"""Independent declaration expectations for the completeness repair."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from ecra.cli import run


class CompleteInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ecra complete ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        cwd = Path.cwd()
        self.addCleanup(lambda: os.chdir(cwd))

    def scan(self, sources, compiled=None, analysis=None, arguments=None, directory=None):
        for name, text in sources.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
        compiled = compiled or [p for p in sources if p.endswith(('.c', '.cpp'))]
        entries = [dict(directory=str(directory or self.root), file=str(self.root / p),
                        arguments=['clang', *(arguments or ['-I'+str(self.root)]), '-c', str(self.root / p)]) for p in compiled]
        (self.root/'compile_commands.json').write_text(json.dumps(entries))
        (self.root/'.ecra').mkdir(exist_ok=True)
        cfg = dict(version=1, analysis=dict(compile_database='compile_commands.json', **(analysis or {})),
                   contexts=[dict(id='main',kind='MAIN',functions=['main'])], review=dict(enabled=False))
        (self.root/'.ecra/semantics.yaml').write_text(json.dumps(cfg))
        with contextlib.redirect_stdout(io.StringIO()):
            code = run(self.root, no_review=True)
        self.assertIn(code, [0,2])
        out = self.root/cfg['analysis'].get('output_dir','.ecra')
        self.facts=json.loads((out/'facts.json').read_text(encoding='utf-8'))
        self.report=json.loads((out/'reports/global_static_concurrency.json').read_text(encoding='utf-8'))
        self.html=(out/'index.html').read_text(encoding='utf-8')
        return self.facts['variables']

    def test_nested_elif_multiline_and_function_scope(self):
        source='''typedef int Value;
/*
#if 0
*/
#if 0
#if 0
int deeply_hidden;
#endif
#endif
#if 0
int arm0;
#elif 1
int arm1;
#elif 0
int arm2;
#else
int last;
#endif
int main(void){
#if (1 && \\
0)
 static Value local_hidden;
#endif
 return 0;
}
'''
        vs=self.scan({'main.c':source})
        for name in ['deeply_hidden','arm0','arm1','arm2','last','local_hidden']:
            hits=[v for v in vs if v['name']==name]
            self.assertEqual(len(hits),1,name)
            self.assertEqual(hits[0]['definition_file'],'main.c')
            expected=next(i for i,line in enumerate(source.splitlines(),1) if name+';' in line)
            self.assertEqual(hits[0]['definition_line'],expected,name)
        local=next(v for v in vs if v['name']=='local_hidden')
        self.assertEqual(local['kind'],'LOCAL_STATIC')
        self.assertEqual(local['coverage_source'],'inactive_branch')
        decision=next(v for v in self.report['risk_summary']['variables'] if v['symbol_id']==local['symbol_id'])
        self.assertEqual(decision['decision'],'supplemental')

    def test_header_real_tu_context_relative_includes(self):
        build=self.root/'build';build.mkdir()
        vs=self.scan({'inc/types.h':'typedef unsigned Word;',
            'inc/hidden.h':'#if 0\nstatic Word header_hidden;\n#endif\n',
            'src/a.c':'#include "types.h"\n#include "hidden.h"\nint main(void){return 0;}',
            'src/b.c':'#include "types.h"\n#include "hidden.h"\n'},
            arguments=['-I../inc'],directory=build)
        hits=[v for v in vs if v['name']=='header_hidden']
        self.assertEqual(len(hits),2)
        self.assertEqual({v['translation_units'][0] for v in hits},{'src/a.c','src/b.c'})
        self.assertTrue(all(v['type']=='Word' for v in hits))
        self.assertFalse(any(u['kind']=='INACTIVE_BRANCH_PARSE_FAILED' for u in self.facts['unknowns']))
        cov={c['file']:c for c in self.report['coverage']['file_coverage']}
        self.assertEqual(cov['inc/types.h']['parse_status'],'PARSED')

    def test_unlisted_cpp_and_header_no_fake_instances(self):
        vs=self.scan({'main.c':'#include "shared.h"\nint main(void){return hs;}',
            'shared.h':'static int hs;',
            'unused.cpp':'#include "shared.h"\nnamespace X { int extra; }\n#if 0\nint extra_hidden;\n#endif',
            'orphan.hpp':'namespace Y { inline int named = 2; }'}, compiled=['main.c'])
        self.assertEqual(len([v for v in vs if v['name']=='hs']),1)
        self.assertTrue({'extra','extra_hidden','named'} <= {v['name'] for v in vs})

    def test_external_empty_file_custom_output_and_build_source(self):
        with tempfile.TemporaryDirectory(prefix='ecra external ') as external:
            path=Path(external)/'empty.h';path.write_text('/* empty */')
            self.scan({'main.c':'int main(void){return 0;}','build/user.c':'int built_user;'},
                analysis=dict(include_dirs=['.',external],output_dir='custom-report'))
            cov={c['file']:c for c in self.report['coverage']['file_coverage']}
            self.assertIn(path.resolve().as_posix(),cov)
            self.assertEqual(cov[path.resolve().as_posix()]['variable_count'],0)
            self.assertIn('build/user.c',cov)
            self.assertFalse(any('custom-report' in f for f in cov))

    def test_partial_const_and_mixed_header_failure(self):
        vs=self.scan({'h.h':'extern const int constant;',
            'good.c':'#include "h.h"\nint main(void){return 0;}',
            'bad.c':'#include "h.h"\nconst int constant=1;\n#include "missing.h"'})
        constant=next(v for v in vs if v['name']=='constant')
        decision=next(v for v in self.report['risk_summary']['variables'] if v['symbol_id']==constant['symbol_id'])
        self.assertEqual(decision['decision'],'unresolved')
        cov={c['file']:c for c in self.report['coverage']['file_coverage']}
        self.assertEqual(cov['h.h']['parse_status'],'PARTIAL')

    def test_vendor_prototype_cannot_hide_user_parameter(self):
        """Parameters are excluded; a vendor prototype must not add inventory rows."""
        vs=self.scan({'vendor/api.h':'void Fn(int count);',
            'app/main.c':'#include "vendor/api.h"\nvoid Fn(int count){}\nint main(void){return 0;}'},
            analysis=dict(include_dirs=['app'],exclude_dirs=['vendor']))
        self.assertFalse(any(v['kind']=='PARAMETER' for v in vs))
        self.assertFalse(any(v['name']=='count' for v in vs))
        # The user translation unit remains in scope and its global is retained.
        self.assertEqual([v['name'] for v in vs if v['kind']=='GLOBAL'], [])

    def test_partial_inactive_and_same_name_unbuilt_definitions(self):
        vs=self.scan({'main.c':'int main(void){return 0;}\n#if 0\nint recovered;\nBadType broken;\n#endif',
            'one.c':'int same=1;', 'two.c':'double same=2;'},compiled=['main.c'])
        self.assertIn('recovered',{v['name'] for v in vs})
        self.assertTrue(any(u['kind']=='INACTIVE_BRANCH_PARSE_FAILED' for u in self.facts['unknowns']))
        same=next(v for v in vs if v['name']=='same')
        self.assertTrue(any(d['file']=='two.c' for d in same['declarations']))
        self.assertEqual(same['supplemental_declarations'][0]['type'],'double')

    def test_conditional_macro_declares_variable_after_branch(self):
        vs=self.scan({'main.c': '#if 0\n#define DECL(n) int n;\n#else\n#define DECL(n)\n#endif\nDECL(hidden_macro)\nint main(void){return 0;}'} )
        hits=[v for v in vs if v['name']=='hidden_macro']
        self.assertEqual(len(hits),1)
        self.assertEqual(hits[0]['definition_file'],'main.c')
        self.assertEqual(hits[0]['definition_line'],6)
