"""Closed-world DIRECT output enforcement; scripted providers, no live requests."""
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import hermes_agent.orchestrator as orchestrator
from hermes_agent.orchestrator import AranAgent
from test_direct_answer_semantics import DirectRouter, Trap

CAPTURE = json.loads((Path(__file__).parent / 'fixtures' / 'direct_train_live_20261014.json').read_text())


def proof(*, facts=(), calculations=(), unknowns=(), examples=()):
    return json.dumps(dict(facts=list(facts), calculations=list(calculations),
                           unknowns=list(unknowns), examples=list(examples)))


class ScriptedLLM:
    def __init__(self, outputs, multi_model=False):
        self.outputs = iter(outputs)
        self.calls = []
        self.multi_model = multi_model

    def is_multi_model_router(self):
        return self.multi_model

    def get_requested_model(self):
        return '9routerpc' if self.multi_model else 'deepseek-chat'

    def analyze(self, **kwargs):
        self.calls.append(kwargs)
        value = next(self.outputs)
        if isinstance(value, Exception):
            raise value
        return {'content': value}


class DirectGroundingTests(unittest.TestCase):
    def run_direct(self, query, outputs, context='', attachments=None, multi_model=False):
        counters = {name: 0 for name in ('planner', 'search', 'fetch', 'facts', 'kg')}
        llm = ScriptedLLM(outputs, multi_model)
        self.last_llm = llm
        agent = AranAgent.__new__(AranAgent)
        agent.router = DirectRouter()
        agent.skill_router = SimpleNamespace(select=lambda _: None)
        agent.user_memory = SimpleNamespace(search=lambda _: [])
        agent.llm = llm
        for field, key in (('task_planner', 'planner'), ('searcher', 'search'),
                           ('skill_bridge', 'fetch'), ('facts', 'facts')):
            setattr(agent, field, Trap(counters, key))

        def kg_trap():
            counters['kg'] += 1
            raise AssertionError('unexpected production KG construction')

        with patch.object(orchestrator, 'TokenProfiler', lambda: object()), \
             patch.object(orchestrator, 'LatencyProfiler', lambda: object()), \
             patch.object(orchestrator, 'log_event', lambda *a, **k: None), \
             patch.object(orchestrator, 'KnowledgeGraph', kg_trap):
            answer = agent.research(query, context=context, attachments=attachments,
                                    request_id='grounding-test')
        self.assertEqual(counters, dict.fromkeys(counters, 0))
        self.assertLessEqual(len(llm.calls), 4 if multi_model else 2)
        return answer, llm

    def run_rejected(self, query, outputs, **kwargs):
        from hermes_agent.direct_provider_recovery import DirectProviderFailure
        with self.assertRaises(DirectProviderFailure) as caught:
            self.run_direct(query, outputs, **kwargs)
        self.assertEqual(caught.exception.failure_class, 'DIRECT_OUTPUT_INVALID')
        self.assertEqual(caught.exception.status_code, 502)
        public = caught.exception.public_error()
        self.assertNotIn('UNKNOWN', public['message'])
        return json.dumps(public), self.last_llm

    def test_exact_captured_train_output_cannot_escape(self):
        answer, llm = self.run_rejected(CAPTURE['query'], [CAPTURE['answer'], CAPTURE['answer']])
        self.assertIn('DIRECT_OUTPUT_INVALID', answer)
        self.assertNotRegex(answer.casefold(), r'\b[48]\s+roda|\b2\s+gerbong')
        self.assertEqual(len(llm.calls), 2)

    def test_generic_missing_parameter_remains_unknown(self):
        query = '3 boxes, total weight? weight per box not given'
        answer, _ = self.run_direct(query, ['Each box weighs 4 kg; total 12 kg.',
                                            proof(unknowns=['weight per box'])])
        self.assertIn('UNKNOWN', answer)
        self.assertIn('weight per box', answer)
        self.assertNotIn('12', answer)

    def test_explicit_user_assumption_is_allowed(self):
        query = '3 boxes; assume 4 units per box. How many units in total?'
        answer, llm = self.run_direct(query, [proof(
            facts=['assume 4 units per box'],
            calculations=[{'expression': '3 * 4', 'result': '12'}])])
        self.assertIn('3 * 4 = 12', answer)
        self.assertNotIn('UNKNOWN', answer)
        self.assertEqual(len(llm.calls), 1)

    def test_fully_supplied_deterministic_derivation_is_allowed(self):
        answer, llm = self.run_direct('7 containers, each has 6 items. Calculate the total.', [proof(
            calculations=[{'expression': '7 * 6', 'result': '42'}])])
        self.assertIn('7 * 6 = 42', answer)
        self.assertEqual(len(llm.calls), 1)

    def test_unrequested_hypothetical_never_becomes_factual_answer(self):
        query = '3 boxes, total weight? weight per box not given'
        answer, _ = self.run_rejected(query, ['If we assume 4 kg per box, the answer is 12 kg.',
                                            proof(examples=[{'expression': '3 * 4', 'result': '12'}])])
        self.assertIn('DIRECT_OUTPUT_INVALID', answer)
        self.assertNotIn('12', answer)

    def test_fractional_arithmetic_preserved_and_discrete_inconsistency_flagged(self):
        query = 'Ada 95 anggota. Jumlahnya berkurang setengahnya. Berapa hasilnya?'
        answer, llm = self.run_direct(query, [proof(
            calculations=[{'expression': 'half(95)', 'result': '47.5'}])])
        self.assertIn('47.5', answer)
        self.assertRegex(answer.casefold(), r'tidak konsisten|inconsisten')
        self.assertEqual(len(llm.calls), 1)

    def test_captured_train_repair_preserves_arithmetic_and_names_both_unknowns(self):
        repaired = proof(calculations=[
            {'expression': '100 - 20 + 15', 'result': '95'},
            {'expression': 'half(r0)', 'result': '47.5'},
            {'expression': 'r1 + pair(5)', 'result': '57.5'},
        ], unknowns=['jumlah gerbong aktual', 'jumlah roda per gerbong'])
        answer, llm = self.run_direct(CAPTURE['query'], [CAPTURE['answer'], repaired])
        self.assertIn('57.5', answer)
        self.assertIn('jumlah gerbong aktual', answer)
        self.assertIn('jumlah roda per gerbong', answer)
        self.assertIn('tidak konsisten', answer)
        self.assertNotRegex(answer, r'\b[48]\s+roda|\b2\s+gerbong')
        self.assertEqual(len(llm.calls), 2)

    def test_equal_numeric_value_cannot_be_reassigned_to_an_unrelated_attribute(self):
        bad = proof(facts=['4 kg per box'])
        answer, _ = self.run_rejected('3 boxes and 4 workers; box weight is missing.', [bad, bad])
        self.assertIn('DIRECT_OUTPUT_INVALID', answer)
        self.assertNotIn('4 kg', answer)

    def test_arithmetic_result_cannot_be_labelled_as_factual_entity_count(self):
        bad = proof(calculations=[{'expression': '60 / 30', 'result': '2', 'label': 'actual compartments'}])
        answer, _ = self.run_rejected('60 items, capacity 30 per compartment; actual count missing.', [bad, bad])
        self.assertIn('DIRECT_OUTPUT_INVALID', answer)
        self.assertNotIn('actual compartments', answer)

    def test_numeric_closure_is_not_grounding(self):
        bad = proof(calculations=[{'expression': '3 * 4', 'result': '12'}])
        answer, _ = self.run_rejected('3 boxes and 20 workers in 5 teams. Weight per box missing.', [bad, bad])
        self.assertIn('DIRECT_OUTPUT_INVALID', answer)
        self.assertNotIn('12', answer)

    def test_implicit_default_in_structured_fact_is_rejected(self):
        bad = proof(facts=['each box has four units'])
        answer, _ = self.run_rejected('3 boxes; units per box not given', [bad, bad])
        self.assertIn('DIRECT_OUTPUT_INVALID', answer)
        self.assertNotIn('four', answer)

    def test_incorrect_arithmetic_is_rejected(self):
        bad = proof(calculations=[{'expression': '7 * 6', 'result': '41'}])
        answer, _ = self.run_rejected('7 containers, each with 6 items.', [bad, bad])
        self.assertIn('DIRECT_OUTPUT_INVALID', answer)
        self.assertNotIn('41', answer)

    def test_requested_hypothetical_is_explicitly_labelled(self):
        answer, llm = self.run_direct('Give a hypothetical example of multiplying quantities.', [proof(
            examples=[{'expression': '3 * 4', 'result': '12'}])])
        self.assertIn('Contoh hipotetis (bukan fakta)', answer)
        self.assertIn('12', answer)
        self.assertEqual(len(llm.calls), 1)

    def test_extra_answer_field_cannot_bypass_safe_renderer(self):
        bad = json.loads(proof())
        bad['answer'] = 'The total is 12 kg.'
        bad = json.dumps(bad)
        answer, _ = self.run_rejected('3 boxes, weight missing.', [bad, bad])
        self.assertIn('DIRECT_OUTPUT_INVALID', answer)
        self.assertNotIn('12', answer)

    def test_previous_assistant_fabrication_is_not_a_supplied_fact(self):
        bad = proof(facts=['each box weighs 4 kg'])
        answer, _ = self.run_rejected('Total weight of 3 boxes?', [bad, bad],
            context='USER: I have 3 boxes.\n\nASSISTANT: each box weighs 4 kg')
        self.assertIn('DIRECT_OUTPUT_INVALID', answer)
        self.assertNotIn('4 kg', answer)

    def test_user_history_and_attachment_are_supported(self):
        answer, llm = self.run_direct('Total weight of 3 boxes?', [proof(
            facts=['each box weighs 4 kg'], calculations=[{'expression': '3 * 4', 'result': '12'}])],
            context='USER: each box weighs 4 kg\n\nASSISTANT: total is 99 kg',
            attachments=[{'content': 'There are 3 boxes.'}])
        self.assertIn('3 * 4 = 12', answer)
        self.assertEqual(len(llm.calls), 1)

    def test_known_repair_provider_failure_is_visible_and_bounded(self):
        from hermes_agent.direct_provider_recovery import DirectProviderFailure
        with self.assertRaises(DirectProviderFailure) as caught:
            self.run_direct('3 boxes, weight missing.',
                [CAPTURE['answer'], RuntimeError('unsupported model')])
        self.assertEqual(caught.exception.failure_class, 'TERMINAL_REQUEST_FAILURE')
        self.assertEqual(len(self.last_llm.calls), 2)

    def test_original_provider_failure_keeps_recovery_error(self):
        from hermes_agent.direct_provider_recovery import DirectProviderFailure
        with self.assertRaises(DirectProviderFailure) as caught:
            self.run_direct('3 boxes, weight missing.', [RuntimeError('unsupported model')])
        self.assertEqual(caught.exception.failure_class, 'TERMINAL_REQUEST_FAILURE')

    def test_programming_error_in_repair_is_visible(self):
        with self.assertRaises(TypeError):
            self.run_direct('3 boxes, weight missing.', ['assume unknown values', TypeError('bug')])

    def test_nonterminating_fraction_remains_exact(self):
        answer, _ = self.run_direct('Divide 1 by 3.', [proof(
            calculations=[{'expression': '1 / 3', 'result': '1/3'}])])
        self.assertIn('1/3', answer)

    def test_code_execution_and_rounding_are_rejected(self):
        for expression in ('__import__("os").system("id")', 'round(95 / 2)', '2 ** 999999'):
            bad = proof(calculations=[{'expression': expression, 'result': '48'}])
            answer, _ = self.run_rejected('Half of 95.', [bad, bad])
            self.assertIn('DIRECT_OUTPUT_INVALID', answer)

    def test_duplicate_json_keys_are_rejected(self):
        bad = '{"facts":[],"facts":["4 kg per box"],"calculations":[],"unknowns":[],"examples":[]}'
        answer, _ = self.run_rejected('3 boxes, weight missing.', [bad, bad])
        self.assertIn('DIRECT_OUTPUT_INVALID', answer)

    def test_decimal_arithmetic_is_exact(self):
        answer, _ = self.run_direct('Add 0.1 and 0.2.', [proof(
            calculations=[{'expression': '0.1 + 0.2', 'result': '0.3'}])])
        self.assertIn('0.1 + 0.2 = 0.3', answer)

    def test_expression_comment_cannot_smuggle_factual_prose(self):
        answer, _ = self.run_direct('3 boxes; assume 4 units per box.', [proof(
            calculations=[{'expression': '3 * 4 # each box weighs 99 kg', 'result': '12'}])])
        self.assertIn('3 * 4 = 12', answer)
        self.assertNotIn('99', answer)
        self.assertNotIn('weighs', answer)

    def test_negated_example_request_is_not_permission_to_assume(self):
        bad = proof(examples=[{'expression': '3 * 4', 'result': '12'}])
        answer, _ = self.run_rejected('3 boxes, weight missing. Do not give hypothetical examples.', [bad, bad])
        self.assertIn('DIRECT_OUTPUT_INVALID', answer)
        self.assertNotIn('12', answer)

    @patch('hermes_agent.direct_provider_recovery.time.sleep')
    def test_generation_and_repair_recovery_preserve_alias_and_bound(self, sleep):
        answer, llm = self.run_direct('3 boxes, total weight? weight per box not given',
            [None, 'If we assume 4 kg, total 12 kg.', None, proof(unknowns=['weight per box'])],
            multi_model=True)
        self.assertIn('UNKNOWN', answer)
        self.assertIn('weight per box', answer)
        self.assertNotIn('12', answer)
        self.assertEqual(len(llm.calls), 4)
        self.assertEqual(llm.calls[0], llm.calls[1])
        self.assertEqual(llm.calls[2], llm.calls[3])
        self.assertTrue(all('model' not in call for call in llm.calls))
        self.assertEqual(sleep.call_count, 2)

    @patch('hermes_agent.direct_provider_recovery.time.sleep')
    def test_repair_provider_exhaustion_never_releases_original(self, sleep):
        from hermes_agent.direct_provider_recovery import DirectProviderFailure
        with self.assertRaises(DirectProviderFailure) as caught:
            self.run_direct('3 boxes, weight missing.',
                ['If we assume 4 kg, total 12 kg.', None, None], multi_model=True)
        self.assertEqual(caught.exception.failure_class, 'PROVIDER_EXHAUSTED')
        self.assertNotIn('12', json.dumps(caught.exception.public_error()))
        self.assertEqual(len(self.last_llm.calls), 3)
        sleep.assert_called_once_with(1.0)

    def test_signed_supplied_values_are_valid_operands(self):
        answer, llm = self.run_direct('Add -3 and 4.', [proof(
            calculations=[{'expression': '-3 + 4', 'result': '1'}])])
        self.assertIn('= 1', answer)
        self.assertEqual(len(llm.calls), 1)

    def test_subtraction_operator_is_not_mistaken_for_an_unsupplied_operand(self):
        answer, llm = self.run_direct('Calculate 12 -3.', [proof(
            calculations=[{'expression': '12 - 3', 'result': '9'}])])
        self.assertIn('12 - 3 = 9', answer)
        self.assertEqual(len(llm.calls), 1)


if __name__ == '__main__':
    unittest.main()
