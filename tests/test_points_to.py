import unittest
import test_ecra


class PointerTests(unittest.TestCase):
    setUp = test_ecra.ProjectTest.setUp
    project = test_ecra.ProjectTest.project
    extract = test_ecra.ProjectTest.extract
    def test_cross_translation_unit_parameters_and_returns(self):
        cfg = self.project({
            'a.c': '''int payload; static int *cached=&payload;
                void store(int *p); int *locate(void){return cached;}
                void Task(void){store(cached);}''',
            'b.c': '''int *locate(void); void store(int *p){*p=7;}
                void ISR(void){*locate()=9;}''',
        })
        facts, _ = self.extract(cfg)
        v = next(v for v in facts['variables'] if v['name'] == 'payload')
        self.assertEqual(set(v['writers']), {'task', 'isr'})
        cached = next(v for v in facts['variables'] if v['name'] == 'cached')
        self.assertEqual(cached['writers'], [])
        self.assertTrue(any(a['via_alias'] == 'interprocedural points-to' for a in v['accesses'] if a.get('via_alias')))

    def test_member_pointer_callback_table_and_field_separation(self):
        cfg = self.project({'a.c': '''
            int first, second, count;
            struct Pair {int *a; int *b;} pair = {&first, &second};
            static void callback(void){count++;}
            static void (*routes[])(void)={callback};
            void Task(void){int *p=pair.a; *p=2; void (*cb)(void)=routes[0]; cb();}
            void ISR(void){*pair.a=3; count++;}
        '''})
        facts, _ = self.extract(cfg)
        by_name = {v['name']: v for v in facts['variables']}
        self.assertEqual(set(by_name['first']['writers']), {'task', 'isr'})
        self.assertEqual(by_name['second']['writers'], [])
        self.assertEqual(set(by_name['count']['writers']), {'task', 'isr'})
        self.assertTrue(any(c['call_kind'] == 'INDIRECT_RESOLVED' and c['callee_name'] == 'callback' for c in facts['calls']))

    def test_memory_wrappers_and_dma_contract(self):
        cfg = self.project({'a.c': '''
            void *memset(void *, int, unsigned); int HAL_UART_Receive_DMA(void *, unsigned char *, unsigned);
            unsigned char samples[32];
            void clear(void *p){memset(p,0,32);}
            void Task(void){clear(samples);}
            void ISR(void){HAL_UART_Receive_DMA(0,samples,32);}
        '''})
        facts, report = self.extract(cfg)
        v = next(v for v in facts['variables'] if v['name'] == 'samples')
        dma_contexts = {c['id'] for c in facts['hardware_contexts'] if c['direction'] == 'rx'}
        self.assertEqual(len(dma_contexts), 1)
        self.assertEqual(set(v['writers']), {'task'} | dma_contexts)
        self.assertTrue(any(a.get('via_api') == 'memset' and a['access_kind'] == 'WRITE' for a in v['accesses']))
        self.assertIn('DMA_SHARED_REVIEW', next(f for f in report['findings'] if f.get('symbol_id') == v['symbol_id'])['rules'])

    def test_wrapped_task_registration_and_atomic_modes(self):
        cfg = self.project({'a.c': '''
            void xTaskCreate(void (*)(void*), const char*);
            _Atomic unsigned published;
            static void service(void *p){__c11_atomic_store(&published, 1, 5);}
            void register_worker(void (*fn)(void*)){xTaskCreate(fn,"worker");}
            void main(void){register_worker(service); register_worker(service);}
            void ISR(void){unsigned x=__c11_atomic_load(&published,5); (void)x;}
        '''}, contexts=[dict(id='isr',kind='ISR',functions=['ISR'])])
        facts, _ = self.extract(cfg)
        v = next(v for v in facts['variables'] if v['name'] == 'published')
        self.assertTrue(v['writers'])
        self.assertIn('isr', v['readers'])
        regs = [r for r in facts['registrations'] if r.get('discovery') == 'points_to']
        self.assertTrue(any(r['may_repeat'] for r in regs))

    def test_multi_hop_pointer_and_unknown_target_stays_visible(self):
        cfg = self.project({'a.c': '''
            int value; int *p=&value; int **pp=&p;
            void write(int **ptr){**ptr=1;}
            void Task(void){write(pp);}
            void ISR(void){int *p=(int*)0x40000000; *p=2;}
        '''})
        facts, _ = self.extract(cfg)
        v = next(v for v in facts['variables'] if v['name'] == 'value')
        self.assertEqual(v['writers'], ['task'])
        self.assertTrue(any(u['kind'] == 'UNRESOLVED_POINTEE' for u in facts['unknowns']))

    def test_array_element_reads_are_not_only_address_escape(self):
        cfg = self.project({'a.c': 'void consume(int); const int lookup[2]={1,2}; int result; void Task(void){result=lookup[result&1];} void ISR(void){consume(lookup[0]);}'})
        facts, _ = self.extract(cfg)
        var = next(v for v in facts['variables'] if v['name']=='lookup')
        self.assertEqual(set(var['readers']), {'task','isr'})
        self.assertEqual(var['writers'], [])

    def test_nested_atomic_macros_with_empty_expansion_tokens(self):
        cfg = self.project({'atomic.h': '#define aload(p) __c11_atomic_load(p,5)\n#define astore(p,v) __c11_atomic_store(p,v,5)\n',
            'a.c': '#include "atomic.h"\n_Atomic unsigned a,b; void Task(void){astore(&a,aload(&b));} void ISR(void){astore(&b,aload(&a));}'})
        facts, _ = self.extract(cfg)
        var = {v['name']:v for v in facts['variables']}
        self.assertEqual(var['a']['writers'], ['task'])
        self.assertEqual(var['b']['writers'], ['isr'])
        self.assertIn('isr',var['a']['readers'])
        self.assertIn('task',var['b']['readers'])
