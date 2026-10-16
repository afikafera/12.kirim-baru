"""Replay captured 9Router proofs and reject unsupported arithmetic/facts offline."""
import json
import unittest
from pathlib import Path

from hermes_agent.direct_answer_grounding import GroundingViolation, validate_and_render
import test_direct_answer_grounding as grounding
import test_direct_grounding_api as api_grounding

proof = grounding.proof

CAPTURE = json.loads((Path(__file__).parent / 'fixtures' / 'direct_9router_equivalence_20261014.json').read_text())


class DirectGroundingEquivalenceTests(unittest.TestCase):
    def run_answer(self, query, content, **kwargs):
        helper = grounding.DirectGroundingTests('test_fractional_arithmetic_preserved_and_discrete_inconsistency_flagged')
        return helper.run_direct(query, [content, content], multi_model=True, **kwargs)

    def run_rejected(self, query, content, **kwargs):
        helper = grounding.DirectGroundingTests('test_fractional_arithmetic_preserved_and_discrete_inconsistency_flagged')
        return helper.run_rejected(query, [content, content], multi_model=True, **kwargs)

    def assert_replay(self, index):
        answer, llm = self.run_answer(CAPTURE['query'], CAPTURE['drafts'][index]['content'])
        self.assertIn('95 / 2 = 47.5', answer)
        self.assertIn('tidak konsisten', answer)
        self.assertIn('jumlah gerbong', answer)
        self.assertIn('jumlah roda per gerbong', answer)
        self.assertNotRegex(answer, r'\b[48]\s+roda|\b2\s+gerbong')
        self.assertEqual(len(llm.calls), 1)

    def test_captured_gpt_oss_lowercase_excerpt(self):
        self.assert_replay(0)

    def test_captured_gpt_oss_repair(self):
        self.assert_replay(1)

    def test_captured_laguna_output(self):
        self.assert_replay(2)

    def test_half_division_is_generic_for_other_values_and_entities(self):
        for query, expression, result in [
            ('73 members; the number becomes half.', '73 / 2', '36.5'),
            ('Ada 66 paket, lalu berkurang setengah.', '66 / 2.0', '33'),
            ('Ada 18 item. Berkurang setengahnya.', '18 / 2', '9'),
        ]:
            with self.subTest(query=query):
                answer, llm = self.run_answer(query, proof(calculations=[{'expression': expression, 'result': result}]))
                self.assertIn('= ' + result, answer)
                self.assertEqual(len(llm.calls), 1)

    def test_nested_half_division_and_intermediate_references(self):
        answer, llm = self.run_answer('Ada 18 lalu ditambah 6 item, kemudian tinggal setengah.', proof(
            calculations=[{'expression': '18 + 6', 'result': '24'},
                          {'expression': 'r0 / 2', 'result': '12'}]))
        self.assertIn('24 / 2 = 12', answer)
        self.assertEqual(len(llm.calls), 1)

    def test_divisor_two_still_requires_supplied_number_or_explicit_half(self):
        bad = proof(calculations=[{'expression': '95 / 2', 'result': '47.5'}])
        answer, llm = self.run_rejected('Ada 95 penumpang. Berapa hasilnya?', bad)
        self.assertNotIn('47.5', answer)
        self.assertIn('DIRECT_OUTPUT_INVALID', answer)
        self.assertEqual(len(llm.calls), 2)

    def test_other_missing_constants_remain_rejected_even_with_half(self):
        for expression, result in [('95 / 4', '23.75'), ('95 * 2', '190'),
                                   ('95 + 2', '97'), ('95 - 2', '93'), ('95 / -2', '-47.5')]:
            with self.subTest(expression=expression):
                with self.assertRaises(GroundingViolation):
                    validate_and_render(proof(calculations=[{'expression': expression, 'result': result}]),
                                        'Ada 95 penumpang, lalu tinggal setengah.', '')

    def test_half_literal_must_be_two_not_arbitrary_denominator(self):
        with self.assertRaises(GroundingViolation):
            validate_and_render(proof(calculations=[{'expression': '95 / (1 + 1)', 'result': '47.5'}]),
                                'Half of 95.', '')

    def test_case_only_excerpt_is_rendered_with_original_source_spelling(self):
        query = 'Delivery Has 17 Containers.'
        answer, llm = self.run_answer(query, proof(facts=['delivery has 17 containers.']))
        self.assertIn('Input yang diberikan: "Delivery Has 17 Containers."', answer)
        self.assertNotIn('"delivery has 17 containers."', answer)
        self.assertEqual(len(llm.calls), 1)

    def test_case_match_with_multiple_source_spellings_is_ambiguous(self):
        with self.assertRaises(GroundingViolation):
            validate_and_render(proof(facts=['AbC']), 'ABC abc', '')

    def test_paraphrase_punctuation_and_whitespace_changes_are_still_rejected(self):
        for quote in ['Each box has four units', 'Each box has 4 units!', 'Each  box has 4 units.']:
            with self.subTest(quote=quote), self.assertRaises(GroundingViolation):
                validate_and_render(proof(facts=[quote]), 'Each box has 4 units.', '')

    def test_unsupplied_wheels_fact_cannot_pass_with_valid_half_calculation(self):
        content = proof(facts=['Setiap gerbong memiliki 4 roda.'],
                        calculations=[{'expression': '95 / 2', 'result': '47.5'}])
        answer, _ = self.run_rejected(CAPTURE['query'], content)
        self.assertIn('DIRECT_OUTPUT_INVALID', answer)
        self.assertNotIn('47.5', answer)
        self.assertNotIn('4 roda', answer)

    def test_wrong_arithmetic_is_not_repaired_locally(self):
        content = proof(calculations=[{'expression': '95 / 2', 'result': '48'}])
        answer, _ = self.run_rejected('Half of 95.', content)
        self.assertIn('DIRECT_OUTPUT_INVALID', answer)
        self.assertNotIn('= 48', answer)

    def test_malicious_left_operand_remains_rejected(self):
        content = proof(calculations=[{'expression': '__import__("os").system("id") / 2', 'result': '47.5'}])
        with self.assertRaises(GroundingViolation):
            validate_and_render(content, 'Half of 95.', '')

    def test_existing_half_function_is_unchanged(self):
        answer, llm = self.run_answer('Ada 95 anggota, lalu tinggal setengahnya.', proof(
            calculations=[{'expression': 'half(95)', 'result': '47.5'}]))
        self.assertIn('95 / 2 = 47.5', answer)
        self.assertEqual(len(llm.calls), 1)

    def test_assistant_half_statement_does_not_supply_operator(self):
        answer, _ = self.run_rejected('Calculate with 95.', proof(
            calculations=[{'expression': '95 / 2', 'result': '47.5'}]),
            context='ASSISTANT: Use half.')
        self.assertIn('DIRECT_OUTPUT_INVALID', answer)
        self.assertNotIn('47.5', answer)

    def test_explicit_divisor_two_without_half_remains_supported(self):
        answer, llm = self.run_answer('Divide 95 by 2.', proof(
            calculations=[{'expression': '95 / 2', 'result': '47.5'}]))
        self.assertIn('95 / 2 = 47.5', answer)
        self.assertEqual(len(llm.calls), 1)


class DirectGroundingEquivalenceApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_captured_outputs_reach_api_and_persistence_without_repair(self):
        helper = api_grounding.DirectGroundingApiTests('test_valid_repair_preserves_fraction_and_missing_input_names')
        for draft in CAPTURE['drafts']:
            with self.subTest(observation=draft['observation_id']):
                response, runs = await helper.send(CAPTURE['query'], [draft['content']])
                self.assertEqual(response.status_code, 200)
                answer = response.json()['choices'][0]['message']['content']
                self.assertIn('95 / 2 = 47.5', answer)
                self.assertIn('jumlah roda per gerbong', answer)
                self.assertIn('tidak konsisten', answer)
                self.assertEqual(len(runs[0].calls), 1)


if __name__ == '__main__':
    unittest.main()
