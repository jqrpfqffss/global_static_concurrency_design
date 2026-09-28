import unittest
import test_ecra


class SerialRegressionTests(unittest.TestCase):
    setUp = test_ecra.ProjectTest.setUp
    project = test_ecra.ProjectTest.project
    extract = test_ecra.ProjectTest.extract

    def test_zero_argument_hal_dispatcher_is_not_a_vector_root(self):
        cfg=self.project({'a.c': '''
            int count;
            void HAL_SYSTICK_IRQHandler(void) { count++; }
            void Task(void) { HAL_SYSTICK_IRQHandler(); }
        '''},contexts=[dict(id='task',kind='TASK',functions=['Task'])])
        facts,report=self.extract(cfg)
        var=next(v for v in facts['variables'] if v['name']=='count')
        self.assertEqual(var['writers'],['task'])
        self.assertFalse(any('HAL_' in c['id'] for c in facts['contexts']))
        self.assertFalse(any('GS-MULTI-CONTEXT' in f['rules'] for f in report['findings']))

    def test_typedef_byte_cast_preserves_scalar_and_field_alias_reads(self):
        cfg=self.project({'a.c': '''
            typedef unsigned char WireByte;
            volatile unsigned long long lifetime;
            volatile struct __attribute__((packed)) {char tag; unsigned value;} sample;
            void Task(void) {
                unsigned sum=0;
                for (unsigned i=0;i<8;i++) sum += ((volatile const WireByte *)&lifetime)[i];
                for (unsigned i=0;i<4;i++) sum += ((volatile const WireByte *)&sample.value)[i];
            }
            void ISR(void) { lifetime++; sample.value=0xababababU; }
        '''})
        facts,report=self.extract(cfg)
        # Struct fields are canonical resources.  The byte-wise alias points
        # at sample.value, not at the whole sample record.
        for name in ('lifetime','sample.value'):
            var=next(v for v in facts['variables'] if v.get('qualified_name', v['name'])==name)
            self.assertIn('task',var['readers'])
            self.assertEqual(var['writers'],['isr'])
            self.assertTrue(any(a['access_kind']=='READ' and a.get('via_alias')=='interprocedural points-to' for a in var['accesses']))
            self.assertIn('GS-MULTI-CONTEXT',next(f for f in report['findings'] if f.get('symbol_id')==var['symbol_id'])['rules'])

    def test_typedef_function_pointer_cast_preserves_callback_target(self):
        cfg=self.project({'a.c': '''
            typedef void (*Callback)(void);
            int count;
            static void CallbackBody(void) { count++; }
            static Callback hook=CallbackBody;
            void Task(void) { ((Callback)hook)(); }
            void ISR(void) { count++; }
        '''})
        facts,_=self.extract(cfg)
        var=next(v for v in facts['variables'] if v['name']=='count')
        self.assertEqual(set(var['writers']),{'task','isr'})
        self.assertTrue(any(c['call_kind']=='INDIRECT_RESOLVED' and c['callee_name']=='CallbackBody' for c in facts['calls']))

    def test_freertos_timer_and_deferred_callbacks_share_serial_daemon(self):
        cfg = self.project({'a.c': '''
            void *xTimerCreate(const char *, unsigned, int, void *, void (*)(void *));
            int xTimerPendFunctionCall(void (*)(void *, unsigned), void *, unsigned, unsigned);
            int count;
            static void Timer(void *p) { count++; }
            static void Deferred(void *p, unsigned n) { count += n; }
            void main(void) {
                xTimerCreate("one", 1, 1, 0, Timer);
                xTimerCreate("two", 2, 1, 0, Timer);
                xTimerPendFunctionCall(Deferred, 0, 1, 0);
            }
        '''}, contexts=[dict(id='main',kind='MAIN',functions=['main'])])
        facts, report = self.extract(cfg)
        count = next(v for v in facts['variables'] if v['name']=='count')
        self.assertEqual(count['writers'], ['auto:freertos:timer_daemon'])
        daemon=next(c for c in facts['contexts'] if c['id']=='auto:freertos:timer_daemon')
        self.assertFalse(daemon['reentrant'])
        self.assertEqual(len(daemon['registrations']),3)
        self.assertFalse(any('GS-MULTI-CONTEXT' in f['rules'] for f in report['findings']))

    def test_timer_callback_called_from_irq_still_has_competing_context(self):
        cfg = self.project({'a.c': '''
            void *xTimerCreate(const char *, unsigned, int, void *, void (*)(void *));
            int count;
            static void Timer(void *p) { count++; }
            void main(void) { xTimerCreate("one",1,1,0,Timer); }
            void USART2_IRQHandler(void) { Timer(0); }
        '''}, contexts=[dict(id='main',kind='MAIN',functions=['main'])])
        facts, report = self.extract(cfg)
        count=next(v for v in facts['variables'] if v['name']=='count')
        self.assertEqual(len(count['writers']),2)
        self.assertTrue(any('GS-MULTI-WRITER' in f['rules'] for f in report['findings']))

    def test_hal_irq_dispatcher_is_not_an_independent_interrupt_root(self):
        cfg = self.project({'a.c': '''
            int count;
            void HAL_UART_IRQHandler(void *handle) { count++; }
            void Task(void) { HAL_UART_IRQHandler(0); }
            void USART2_IRQHandler(void) { HAL_UART_IRQHandler(0); }
        '''}, contexts=[dict(id='task', kind='TASK', functions=['Task'])])
        facts, _ = self.extract(cfg)
        count = next(v for v in facts['variables'] if v['name'] == 'count')
        self.assertEqual(len(count['writers']), 2)
        self.assertTrue(any(c.startswith('auto:USART2_IRQHandler:') for c in count['writers']))
        self.assertFalse(any('HAL_UART_IRQHandler' in c['id'] for c in facts['contexts']))
        self.assertTrue(all(len(path)==2 for a in count['accesses'] for path in a['call_chains'].values()))

    def test_task_only_irq_named_helper_does_not_create_a_race(self):
        cfg = self.project({'a.c': '''
            int count;
            void Device_IRQHandler(int channel) { count++; }
            void Task(void) { Device_IRQHandler(1); }
        '''}, contexts=[dict(id='task', kind='TASK', functions=['Task'])])
        facts, report = self.extract(cfg)
        count = next(v for v in facts['variables'] if v['name'] == 'count')
        self.assertEqual(count['writers'], ['task'])
        self.assertFalse(any('GS-MULTI-CONTEXT' in f['rules'] for f in report['findings']))

    def test_single_read_write_or_context_is_explicitly_screened(self):
        cfg = self.project({'a.c': '''
            int only_read, only_write, local_state;
            void Task(void) { int snapshot = only_read; only_write = snapshot; local_state++; }
        '''}, contexts=[dict(id='task', kind='TASK', functions=['Task'])])
        facts, report = self.extract(cfg)
        variables = {v['name']: v for v in facts['variables']}
        for name in ('only_read', 'only_write', 'local_state'):
            self.assertEqual(variables[name]['audit_status'], 'SCREENED_NO_CONCURRENCY_RISK')
            self.assertFalse(any(f.get('symbol_id') == variables[name]['symbol_id'] for f in report['findings']))
        self.assertEqual(variables['only_read']['screening_reason'], 'SAFE_READ_ONLY')
        self.assertEqual(variables['only_write']['screening_reason'], 'SAFE_SINGLE_CONTEXT')

    def test_configured_irq_callback_registration_creates_real_isr_context(self):
        cfg = self.project({'a.c': '''
            typedef void (*Callback)(void);
            void BSP_RegisterIrqCallback(int channel, Callback callback);
            int count;
            static void AdcDone(void) { count++; }
            void Task(void) { BSP_RegisterIrqCallback(0, AdcDone); count++; }
        '''}, contexts=[dict(id='task', kind='TASK', functions=['Task'])])
        cfg['entry_registrations'] = [dict(api='BSP_RegisterIrqCallback', callback_arg=1,
                                           kind='ISR', context_id='adc_irq', may_repeat=False)]
        facts, report = self.extract(cfg)
        count = next(v for v in facts['variables'] if v['name'] == 'count')
        self.assertEqual(set(count['writers']), {'task', 'adc_irq'})
        irq = next(c for c in facts['contexts'] if c['id'] == 'adc_irq')
        self.assertEqual(irq['kind'], 'ISR')
        self.assertTrue(any('GS-MULTI-WRITER' in f['rules'] for f in report['findings'] if f.get('symbol_id') == count['symbol_id']))
