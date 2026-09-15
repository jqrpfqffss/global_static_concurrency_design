import unittest
from html.parser import HTMLParser

from ecra.review_presentation import explanation, paragraphs, process


class VisibleText(HTMLParser):
    """Read what a user gets without opening any details."""
    def __init__(self, content):
        super().__init__()
        self.depth, self.parts = 0, []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        if tag == 'details':
            self.depth += 1

    def handle_endtag(self, tag):
        if tag == 'details':
            self.depth -= 1

    def handle_data(self, text):
        if not self.depth:
            self.parts.append(text)


class PresentationTests(unittest.TestCase):
    def test_whole_cause_process_result_and_fix_are_visible_without_clicks(self):
        answer = dict(reason='独立复核依据', impact='两次自增只计一次；业务影响未证实。',
                      interleaving='(1) main 读 N；(2) USART2 抢占后写 N+1；(3) main 恢复后写 N+1。',
                      protection='只屏蔽 DMA 中断，USART2 仍可抢占。', fix='保存屏蔽状态，保护完整读改写再恢复。',
                      verification='待做板上验证。')
        rendered = explanation(answer, 'confirmed')
        visible = ''.join(VisibleText(rendered).parts)
        for key in ['impact', 'protection', 'fix']:
            for part in paragraphs(answer[key]):
                self.assertIn(part, visible)
        for part in ['main 读 N', 'USART2 抢占后写 N+1', 'main 恢复后写 N+1', '业务影响未证实']:
            self.assertIn(part, visible)
        self.assertLess(visible.index('main 读 N'), visible.index('USART2 抢占后写 N+1'))
        self.assertLess(visible.index('USART2 抢占后写 N+1'), visible.index('main 恢复后写 N+1'))
        self.assertNotIn(answer['reason'], visible)
        self.assertIn('不代表已经实测', rendered)

    def test_preserves_negative_branches_and_does_not_turn_call_edges_into_steps(self):
        original = '(1) main 开始 DMA；(2) DMA 读缓冲区；(3) CPU 改写。(4) 已排除：完成中断返回前 main 不能运行。'
        rendered = ''.join(VisibleText(process(original)).parts)
        self.assertEqual(''.join(rendered.split()), ''.join(original.split()))
        plain = 'IRQ→HAL→回调；同级中断不能互抢。'
        self.assertNotIn('step-number', process(plain))
        self.assertEqual(''.join(VisibleText(process(plain)).parts), plain)
        self.assertEqual(paragraphs('for(i=0;i<3;i++)（条件；仍成立）；结果。'), ['for(i=0;i<3;i++)（条件；仍成立）；', '结果。'])
        priorities = '1) USART2（抢占优先级7）更新 H+1；2) TIM3（优先级2，可抢占7）读取 (H+1)；3) 返回。'
        formatted = process(priorities)
        self.assertEqual(formatted.count('class="step-number"'), 3)
        self.assertIn('USART2（抢占优先级7）', formatted)

    def test_safe_missing_and_gap_results_never_invent_a_conflict(self):
        answer = dict(interleaving='同级中断串行执行，不能互相抢占。', protection='保持同级优先级。', impact='该候选没有冲突。', fix='保持保护。')
        safe = explanation(answer, 'safe')
        self.assertIn('为什么这次不会形成冲突', safe)
        self.assertNotIn('并发怎样发生', safe)
        self.assertNotIn('process-step', safe)
        self.assertIn('尚无有效复核结论', explanation({}, 'unresolved'))
        self.assertIn('不能据此补造', process(''))
        gap = explanation(answer, 'confirmed', False)
        self.assertIn('这处证据说明了什么', gap)
        self.assertNotIn('并发怎样发生', gap)
        self.assertNotIn('<script>', process('① <script>bad()</script>；② 返回。'))


if __name__ == '__main__':
    unittest.main()
