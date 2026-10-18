"""Replay selected source interleavings on a host, independently of AI verdicts.

This is a bounded scheduling model, not an STM32 peripheral emulator or board
test. Each hook is inserted into a copy of the actual ARM fixture, exactly once.
The original firmware sources and model-readable projects are never modified.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/stm32_cdc'

# (source anchor, replacement, setup, independently checked observation)
REPLAYS = {
 'p01': ('g_shared = v;', 'Lab_Inject(); g_shared = v;', 'g_shared=1;', 'g_shared==1 && fired==1'),
 'p02': ('g_shared = v;', 'Lab_Inject(); g_shared = v;', 'g_shared=1;', 'g_shared==1 && fired==1'),
 'p03': ('SetValue(previous);', 'Lab_Inject(); SetValue(previous);', 'g_shared=1;', 'g_shared==1 && fired==1'),
 'p04': ('SetValue(v);', 'Lab_Inject(); SetValue(v);', 'g_shared=1;', 'g_shared==1 && fired==1'),
 'p05': ('g_shared.length = 16;', 'g_shared.length = 16; Lab_Inject();', '', 'observed==1 && fired==1'),
 'p06': ('Forward(&g_shared, &saved);', 'Lab_Inject(); Forward(&g_shared, &saved);',
         'g_shared.value=1;', 'g_shared.value==1 && g_shared.version==0 && fired==1'),
 'p07': ('publish(v);', 'Lab_Inject(); publish(v);', 'g_shared=1;', 'g_shared==1 && fired==1'),
 'p08': ('g_shared = next;', 'Lab_Inject(); g_shared = next;', 'g_shared=1;', 'g_shared==2 && fired==1'),
 'p09': ('uint32_t value = p->value;', 'Lab_Inject(); uint32_t value = p->value;', '',
         'delivery_generation==1 && delivered==20 && g_shared.generation==2 && fired==1'),
 'p11': ('__NOP();', 'Lab_Nop();', '', 'stalled==1 && g_shared==0 && attempts==16'),
 'p12': ('memcpy(output, payload, g_shared);',
         '{ Lab_Inject(); Lab_CheckedCopy(output, payload, g_shared); }', '', 'copy_size==32 && fired==1'),
 'p13': ('SetValue(saved);', 'Lab_Inject(); SetValue(saved);', 'g_shared=1;', 'g_shared==200 && blocked==1'),
 'p14': ('g_shared = v;', 'Lab_Inject(); g_shared = v;', 'g_shared=1;', 'g_shared==200 && blocked==1'),
 'p15': ('SetValue(v);', 'Lab_Inject(); SetValue(v);', 'g_shared=1;', 'g_shared==200 && blocked==1'),
}

HEADER = r'''
#include <stdint.h>
#include <string.h>
#include <stddef.h>
void Lab_Low(void); void Lab_High(void); void Lab_OnTick(void);
void Lab_Configure(uint32_t, uint32_t); void Lab_Inject(void); void Lab_Nop(void);
void Lab_CheckedCopy(void *, const void *, size_t);
void HAL_NVIC_SetPriority(int, uint32_t, uint32_t);
uint32_t __get_PRIMASK(void); void __disable_irq(void); void __set_PRIMASK(uint32_t);
uint32_t __get_BASEPRI(void); void __set_BASEPRI(uint32_t);
#define SysTick_IRQn (-1)
#define __DSB() ((void)0)
#define __ISB() ((void)0)
'''

RUNTIME = r'''
#include <stdio.h>
#include <setjmp.h>
static uint32_t primask, basepri, low_priority, high_priority, tick_priority=15;
static int attempted, fired, blocked, pending, attempts, stalled;
static size_t copy_size;
static jmp_buf escape_loop;
void Lab_Configure(uint32_t low, uint32_t high) { low_priority=low; high_priority=high; }
uint32_t __get_PRIMASK(void) { return primask; }
void __disable_irq(void) { primask=1; }
void __set_PRIMASK(uint32_t mask) { primask=mask; }
uint32_t __get_BASEPRI(void) { return basepri; }
void __set_BASEPRI(uint32_t mask) { basepri=mask; }
void HAL_NVIC_SetPriority(int irq, uint32_t priority, uint32_t sub) { tick_priority=priority; }
void Lab_Inject(void) {
 if (attempted++) return;
 if (primask || (basepri && (high_priority<<4)>=basepri) || high_priority>=low_priority) {
  blocked++; pending=1; return;
 }
 fired++; Lab_High();
}
void Lab_Nop(void) {
 /* SysTick can only execute if it can preempt the active high IRQ. */
 attempts++;
 if (tick_priority<high_priority && !primask && (!basepri || (tick_priority<<4)<basepri)) Lab_OnTick();
 if (attempts>=16) { stalled=1; longjmp(escape_loop,1); }
}
void Lab_CheckedCopy(void *to, const void *from, size_t size) { copy_size=size; }
'''


def replay(output: Path, compiler: str):
    output.mkdir(parents=True, exist_ok=True)
    results=[]
    for name,(anchor,replacement,setup,check) in REPLAYS.items():
        original=(FIXTURES/(name+'.c')).read_text(encoding='utf-8')
        if original.count(anchor)!=1:
            raise ValueError(f'{name}: injection anchor must match exactly once')
        source=original.replace(anchor,replacement)
        folder=output/name
        folder.mkdir(exist_ok=True)
        (folder/'lab.h').write_text(HEADER,encoding='utf-8')
        # Include the instrumented original in the same TU so checks can inspect
        # its real static storage. No implementation of its logic is mirrored.
        (folder/'scenario.c').write_text(source,encoding='utf-8')
        invocation='if (!setjmp(escape_loop)) Lab_High();' if name=='p11' else 'Lab_Low();'
        code='#include "lab.h"\n'+RUNTIME+'\n#include "scenario.c"\n'
        if name!='p11':code+='void Lab_OnTick(void) {}\n'
        code+=f'''int main(void) {{
 Lab_Init(); {setup} {invocation}
 if (pending) {{ pending=0; Lab_High(); }}
 int ok=({check});
 printf("ok=%d fired=%d blocked=%d attempts=%d copy_size=%u\\n",ok,fired,blocked,attempts,(unsigned)copy_size);
 return !ok;
}}
'''
        driver=folder/'driver.c'
        driver.write_text(code,encoding='utf-8')
        binary=folder/'replay.exe'
        build=subprocess.run([compiler,'-std=c11','-O0',str(driver),'-o',str(binary)],capture_output=True,text=True)
        (folder/'build.txt').write_text(build.stdout+build.stderr,encoding='utf-8')
        if build.returncode:raise RuntimeError(f'{name}: see {folder}/build.txt')
        run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)
        row=dict(case=name,passed=run.returncode==0,observation=run.stdout.strip(),
                 source_sha256=hashlib.sha256(original.encode()).hexdigest(),
                 injection=dict(anchor=anchor,replacement=replacement),check=check)
        results.append(row)
        print(name,row['observation'],flush=True)
    (output/'results.json').write_text(json.dumps(dict(
        limitation='Host scheduling model with explicit hooks; no peripheral emulation or on-board execution.',
        compiler=compiler,results=results),indent=2),encoding='utf-8')
    if not all(r['passed'] for r in results):raise RuntimeError('An independent replay failed')
    return results


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'validation/stm32_cube_cdc_20261018/host-replays')
    parser.add_argument('--cc',default=shutil.which('gcc') or shutil.which('clang'))
    args=parser.parse_args()
    if not args.cc:raise RuntimeError('A native C compiler is required')
    replay(args.out.resolve(),args.cc)
