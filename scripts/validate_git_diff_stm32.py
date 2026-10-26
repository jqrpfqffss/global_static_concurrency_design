"""Reproducible Cortex-M7 build/scan integration benchmark, never a hardware test.

Uses real STM32H743 CMSIS headers and an actual ARM GCC ELF build. Generated
application modules exercise deep calls, static identities, shared data, IRQs,
callbacks, DMA registers and critical sections. No existing firmware is edited.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import threading

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
from ecra.common import read_json, write_json


def command(root, *args):
    proc = subprocess.run(list(map(str, args)), cwd=root, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, encoding='utf-8', errors='replace')
    if proc.returncode:
        raise RuntimeError(proc.stdout[-6000:])
    return proc.stdout.strip()


def create(root, cmsis, compiler, count):
    if root.exists():
        raise ValueError('验证目录必须不存在，防止覆盖既有工程：' + str(root))
    root.mkdir(parents=True)
    device = cmsis/'STM32H7/Drivers/CMSIS/Device/ST/STM32H7xx/Include'
    core = cmsis/'CMSIS/Core/Include'
    if not (device/'stm32h743xx.h').is_file() or not (core/'core_cm7.h').is_file():
        raise ValueError('需要实际 STM32H7 和 CMSIS Core 头文件')
    header = '#define BENCH_VALUE 1\nstruct State {unsigned raw,filtered;};\n'
    for i in range(count):
        header += f'extern struct State state_{i}; void Step_{i}(void);\n'
    header += 'extern unsigned dma_buffer[32];\n'
    (root/'app.h').write_text(header)
    for i in range(count):
        next_call = f'Step_{i+1}();' if i % 32 != 31 and i+1 < count else ''
        text = f'''#include "app.h"
struct State state_{i}; static unsigned file_state;
static void Filter_{i}(unsigned *out){{static unsigned history;history+=state_{i}.raw;*out=history;}}
void Step_{i}(void){{state_{i}.raw+=BENCH_VALUE;Filter_{i}(&state_{i}.filtered);file_state++;{next_call}}}
'''
        (root/f'module_{i:03d}.c').write_text(text)
    entries = ''.join(f'Step_{i}();' for i in range(0, count, 32))
    (root/'main.c').write_text('''#include "stm32h7xx.h"
#include "app.h"
unsigned dma_buffer[32]; static void (*callback)(void)=Step_0;
void HAL_NVIC_SetPriority(IRQn_Type irq,unsigned priority,unsigned sub){(void)sub;NVIC_SetPriority(irq,priority);}
void ECAT_IRQHandler(void){callback();}
void TIM4_IRQHandler(void){__disable_irq();Step_0();__enable_irq();}
void DMA1_Stream0_IRQHandler(void){dma_buffer[0]++;}
int main(void){HAL_NVIC_SetPriority(TIM4_IRQn,1,0);NVIC_EnableIRQ(TIM4_IRQn);
DMA1_Stream0->M0AR=(unsigned)dma_buffer;DMA1_Stream0->NDTR=32;
while(1){''' + entries + '''}}
void Reset_Handler(void){main();}
__attribute__((section(".isr_vector"),used)) void (*const vectors[])(void)={
(void(*)(void))0x24080000,Reset_Handler,ECAT_IRQHandler,TIM4_IRQHandler,DMA1_Stream0_IRQHandler};
''')
    (root/'firmware.ld').write_text('''ENTRY(Reset_Handler)
MEMORY { FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 2048K
RAM (rwx) : ORIGIN = 0x24000000, LENGTH = 512K }
SECTIONS { .isr_vector : {KEEP(*(.isr_vector))} > FLASH
.text : {*(.text*) *(.rodata*)} > FLASH
.data : {*(.data*)} > RAM AT>FLASH
.bss : {*(.bss*) *(COMMON)} > RAM }
''')
    (root/'CMakeLists.txt').write_text(f'''cmake_minimum_required(VERSION 3.22)
set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_C_COMPILER "{compiler.as_posix()}")
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)
project(ecra_h743 C)
file(GLOB modules CONFIGURE_DEPENDS "module_*.c")
add_executable(firmware main.c ${{modules}})
target_include_directories(firmware PRIVATE "{device.as_posix()}" "{core.as_posix()}")
target_compile_definitions(firmware PRIVATE STM32H743xx)
target_compile_options(firmware PRIVATE -mcpu=cortex-m7 -mthumb -O0 -ffunction-sections -fdata-sections)
target_link_options(firmware PRIVATE -mcpu=cortex-m7 -mthumb -nostdlib -T${{CMAKE_SOURCE_DIR}}/firmware.ld -Wl,-Map=${{CMAKE_BINARY_DIR}}/firmware.map -Wl,--gc-sections)
''')
    (root/'.gitignore').write_text('build/\n.ecra*/\n')
    command(root, 'git', 'init')
    command(root, 'git', 'config', 'user.email', 'ecra@example.invalid')
    command(root, 'git', 'config', 'user.name', 'ECRA integration')
    command(root, 'git', 'add', '.')
    command(root, 'git', 'commit', '-m', 'STM32H743 baseline integration firmware')
    command(root, 'git', 'branch', 'base')


def scan(root, config, name, mode):
    import psutil
    log = root.parent/(root.name+'-'+name+'.log')
    begin, peak = time.monotonic(), 0
    with log.open('w', encoding='utf-8') as stream:
        proc = subprocess.Popen([sys.executable, '-B', str(TOOL/'run_ecra.py'), '--project', str(root),
            '--config', str(config), '--scan-mode', mode, '--no-review'], stdout=stream, stderr=subprocess.STDOUT,
            env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        while proc.poll() is None:
            try:
                parent = psutil.Process(proc.pid)
                peak = max(peak, sum(p.memory_info().rss for p in [parent, *parent.children(recursive=True)] if p.is_running()))
            except psutil.Error:
                pass
            time.sleep(.2)
    result = dict(name=name, exit_code=proc.returncode, seconds=time.monotonic()-begin, peak_rss_bytes=peak, log=str(log))
    out = root/'.ecra'
    validity = read_json(out/'result_validity.json')
    result['validity'] = validity
    if proc.returncode not in (0, 1, 2) or not validity.get('analysis_valid'):
        raise RuntimeError('验证扫描失败：' + str(log))
    from ecra.workflow import read_saved_json
    from ecra.git_diff import summarize
    facts = read_saved_json(out/'facts.json', canonical_accesses=True)
    report = read_saved_json(out/'reports/global_static_concurrency.json')
    summary = summarize(facts, report)
    diff = report.get('git_diff', {})
    result.update(translation_units=len(facts['translation_units']), variables=len(facts['variables']),
        selected=len(diff.get('selected_symbol_ids', [])), cache=diff.get('tu_cache'),
        fallback=diff.get('fallback_reasons'), static_status=report['analysis_status'],
        review_targets=report['review_integrity']['targets'], verification=diff.get('full_verification'))
    result['stage_timings'] = read_json(out/'diagnostics/scan_stages.json')
    result['cache_hit_rate'] = ((result['cache']['hits']/result['cache']['total']) if result.get('cache') and result['cache']['total'] else 0)
    write_json(root.parent/(root.name+'-'+name+'-execution.json'), result)
    write_json(root.parent/(root.name+'-'+name+'-summary.json'), summary, indent=None)
    return result, summary


def main():
    parser = argparse.ArgumentParser(description='构建并验证 STM32H743 多 TU 差异扫描夹具')
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--vendor', type=Path, required=True, help='包含 STM32H7 和 CMSIS 子目录的真实供应商头文件根目录')
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--units', type=int, default=128)
    args = parser.parse_args()
    root = args.work.resolve()
    create(root, args.vendor.resolve(), args.compiler.resolve(), args.units)
    cfg = dict(version=1, project=dict(root=str(root), chip='STM32H743xx', core='Cortex-M7'),
        analysis=dict(cmake=dict(build_dir='build/ecra', generator='Ninja', build=True, clean_before_configure=False),
            build_closure_only=True, auto_system_includes=True, extraction_workers=8, output_dir='.ecra',
            git_diff=dict(target_ref='base', compare_mode='direct', verify_against_full=False)),
        contexts=[dict(id='main', kind='MAIN', functions=['main'])], review=dict(enabled=False, prepare_packets=False))
    config = root.parent/(root.name+'-semantics.yaml')
    write_json(config, cfg)
    results = []
    baseline, _ = scan(root, config, 'full-base', 'full')
    results.append(baseline)
    module = root/'module_000.c'
    module.write_text(module.read_text().replace('+=BENCH_VALUE', '+=BENCH_VALUE+1'))
    command(root, 'git', 'add', module.name)
    command(root, 'git', 'commit', '-m', 'change upstream data calculation')
    for name in ('diff-first', 'diff-cached'):
        result, current = scan(root, config, name, 'diff')
        results.append(result)
    full, full_summary = scan(root, config, 'full-head', 'full')
    results.append(full)
    if current != full_summary:
        raise RuntimeError('当前版本独立全量与差异语义摘要不一致')
    for name, file, old, new in [('diff-header', 'app.h', '#define BENCH_VALUE 1', '#define BENCH_VALUE 2'),
                                  ('diff-nvic', 'main.c', 'TIM4_IRQn,1,0', 'TIM4_IRQn,0,0')]:
        path = root/file
        path.write_text(path.read_text().replace(old, new))
        command(root, 'git', 'add', file)
        command(root, 'git', 'commit', '-m', name)
        result, _ = scan(root, config, name, 'diff')
        results.append(result)
    cfg['analysis']['git_diff']['verify_against_full'] = True
    write_json(config, cfg)
    result, _ = scan(root, config, 'diff-full-verification', 'diff')
    results.append(result)
    write_json(root.parent/(root.name+'-acceptance.json'), dict(complete=True, scope='生成的真实 ARM GCC/CMSIS 集成夹具；不是生产工程或硬件时序验证', runs=results,
        classification_mismatches=0, semantic_mismatches=0, head=command(root, 'git', 'rev-parse', 'HEAD')))
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
