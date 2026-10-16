"""Offline DIRECT matrix: arithmetic, units, clocks and malformed output."""
import copy
import json
import unittest

import test_direct_answer_grounding as legacy
import test_direct_grounding_api as api_fixture
from hermes_agent.direct_answer_grounding import validate_and_render, GroundingViolation
from hermes_agent.direct_provider_recovery import DirectProviderFailure, analyze_direct

TANK = ('Sebuah tangki air berkapasitas 1.500 liter dalam keadaan kosong. '
        'Pipa mengisi 250 mililiter per detik, kebocoran 3 liter setiap 5 menit. '
        'Mulai pukul 08.00 pagi. Setiap 500 liter menambah berat 0,5 ton. '
        'Berapa waktu penuh dan berat dalam kilogram?')
TANK_PLAN = {
    'v': 2, 'q': ['1.500 liter', '250 mililiter per detik',
                 '3 liter setiap 5 menit', '08.00 pagi', '500 liter', '0,5 ton'],
    's': [['-', 1, 2], ['/', 0, 6], ['+', 3, 7], ['/', 0, 4], ['*', 9, 5]],
    'o': [[8, 'clock'], [10, 'kg']], 'u': [],
}


def plan(q, s=(), o=(), u=()):
    return {'v': 2, 'q': list(q), 's': list(s), 'o': list(o), 'u': list(u)}


def render(source, record):
    return validate_and_render(json.dumps(record), source, source)


class DirectCalculationPlanTests(unittest.TestCase):
    def test_tank_calculation_returns_exact_clock_and_kg(self):
        answer = render(TANK, TANK_PLAN)
        self.assertIn('09:44:10', answer)
        self.assertIn('1500 kg', answer)
        self.assertNotIn('UNKNOWN', answer)

    def test_changed_values_and_other_entities_are_not_hardcoded(self):
        cases = [
            ('Sebuah wadah 720 liter. Masuk 200 mililiter per detik, bocor 2 liter setiap 5 menit.',
             ['720 liter', '200 mililiter per detik', '2 liter setiap 5 menit'], '1800/29'),
            ('Sebuah bak 360 liter. Masuk 150 mililiter per detik, bocor 3 liter setiap 10 menit.',
             ['360 liter', '150 mililiter per detik', '3 liter setiap 10 menit'], '1200/29'),
        ]
        for source, inputs, minutes in cases:
            with self.subTest(source=source):
                answer = render(source, plan(inputs, [['-', 1, 2], ['/', 0, 3]], [[4, 'menit']]))
                self.assertIn(minutes + ' menit', answer)

    def test_metric_conversion_matrix(self):
        cases = [
            ('Convert 250 milliliters.', '250 milliliters', 'L', '0.25 L'),
            ('Convert 2 kilograms.', '2 kilograms', 'g', '2000 g'),
            ('Ada 1.500 gram. Berapa kg?', '1.500 gram', 'kg', '1.5 kg'),
            ('Convert 0.5 tonnes.', '0.5 tonnes', 'kg', '500 kg'),
            ('Convert 90 minutes.', '90 minutes', 'jam', '1.5 jam'),
            ('Ada 1,25 kilometer. Berapa meter?', '1,25 kilometer', 'm', '1250 m'),
            ('Convert 72 km/h.', '72 km/h', 'm/s', '20 m/detik'),
        ]
        for source, quote, target, expected in cases:
            with self.subTest(source=source):
                self.assertIn(expected, render(source, plan([quote], o=[[0, target]])))

    def test_decimal_with_two_fraction_digits_is_not_a_clock(self):
        for token, result in [('1.50', '3.5'), ('0.50', '2.5')]:
            with self.subTest(token=token):
                self.assertIn(result, render('Add ' + token + ' and 2.', plan(
                    [token, '2'], [['+', 0, 1]], [[2, '']])))

    def test_dotted_clock_needs_a_clock_marker(self):
        self.assertIn('08:00:00', render('Mulai pukul 08.00.', plan(
            ['pukul 08.00'], o=[[0, 'clock']])))
        with self.assertRaises(GroundingViolation):
            render('Add 1.50.', plan(['1.50'], o=[[0, 'clock']]))

    def test_percent_is_a_unit_conversion_not_an_invented_number(self):
        answer = render('Ada 500 liter; ambil 20%. Berapa liter?', plan(
            ['500 liter', '20%'], [['*', 0, 1]], [[2, 'L']]))
        self.assertIn('100 L', answer)

    def test_clock_rollover_preserves_next_day(self):
        answer = render('Start 23:50 and add 20 minutes.', plan(
            ['23:50', '20 minutes'], [['+', 0, 1]], [[2, 'clock']]))
        self.assertIn('00:10:00 (+1 hari)', answer)

    def test_clock_fractional_seconds_remain_exact(self):
        answer = render('Start 08:00. Divide 1 second by 3.', plan(
            ['08:00', '1 second', '3'], [['/', 1, 2], ['+', 0, 3]], [[4, 'clock']]))
        self.assertIn('08:00:00 + 1/3 detik', answer)

    def test_arithmetic_decimal_and_fraction_results_are_computed_by_code(self):
        self.assertIn('0.3', render('Add 0.1 and 0.2.', plan(
            ['0.1', '0.2'], [['+', 0, 1]], [[2, '']])))
        self.assertIn('1/3', render('Divide 1 by 3.', plan(
            ['1', '3'], [['/', 0, 1]], [[2, '']])))

    def test_fractional_people_and_genuine_missing_inputs_remain_distinct(self):
        answer = render('Ada 95 penumpang, berkurang setengah. Berapa roda? Jumlah gerbong tidak diberikan.',
                        plan(['95 penumpang'], [['half', 0]], [[1, 'penumpang']],
                             ['jumlah gerbong', 'jumlah roda per gerbong']))
        self.assertIn('47.5 orang', answer)
        self.assertIn('tidak konsisten', answer)
        self.assertIn('UNKNOWN', answer)

    def test_source_values_cannot_be_relabelled_as_other_dimensions(self):
        with self.assertRaises(GroundingViolation):
            render('Ada 80 km/h. Berapa roda?', plan(['80 km/h'], o=[[0, 'roda']]))
        with self.assertRaises(GroundingViolation):
            render('3 boxes and 4 workers; weight missing.', plan(
                ['3 boxes', '4 workers'], [['*', 0, 1]], [[2, 'kg']]))

    def test_unit_and_quantity_must_be_in_same_source_excerpt(self):
        with self.assertRaises(GroundingViolation):
            render('Ada 3 kotak dan 4 orang. Berat kg tidak diberikan.', plan(['4 kg'], o=[[0, 'kg']]))

    def test_numeric_substrings_are_not_supplied_inputs(self):
        for quote in ['5', '0.5', '500']:
            with self.subTest(quote=quote), self.assertRaises(GroundingViolation):
                render('Calculate with 95 and 10.5 and 1500.', plan([quote], o=[[0, '']]))

    def test_source_sign_must_not_be_dropped(self):
        with self.assertRaises(GroundingViolation):
            render('Add -3 and 4.', plan(['3'], o=[[0, '']]))
        self.assertIn('1', render('Add -3 and 4.', plan(
            ['-3', '4'], [['+', 0, 1]], [[2, '']])))

    def test_wrong_dimensions_and_invalid_operations_are_rejected(self):
        cases = [
            plan(['1 liter', '2 kg'], [['+', 0, 1]], [[2, 'L']]),
            plan(['1 liter'], [['__import__', 0]], [[1, 'L']]),
            plan(['1 liter'], [['+', 0, 2]], [[1, 'L']]),
            plan(['1 liter'], [['+', 0, True]], [[1, 'L']]),
            plan(['1 liter'], o=[[False, 'L']]),
        ]
        for record in cases:
            with self.subTest(record=record), self.assertRaises(GroundingViolation):
                render('Calculate 1 liter and 2 kg.', record)

    def test_unsupported_units_are_not_guessed(self):
        with self.assertRaises(GroundingViolation):
            render('Convert 1 gallon.', plan(['1 gallon'], o=[[0, 'L']]))

    def test_ambiguous_and_malformed_number_formats_are_rejected(self):
        for source, quote in [('1.500 L', '1.500 L'),
                              ('Ada 1.50 liter. Berapa?', '1.50 liter'),
                              ('Convert 1,50 liters.', '1,50 liters')]:
            with self.subTest(source=source), self.assertRaises(GroundingViolation):
                render(source, plan([quote], o=[[0, 'L']]))

    def test_zero_net_rate_cannot_produce_a_fill_time(self):
        with self.assertRaises(GroundingViolation):
            render('Ada 10 liter; 5 liter per menit masuk dan 5 liter per menit bocor.', plan(
                ['10 liter', '5 liter per menit', '5 liter per menit'],
                [['-', 1, 2], ['/', 0, 3]], [[4, 'menit']]))

    def test_invalid_clocks_and_model_results_fields_are_rejected(self):
        with self.assertRaises(GroundingViolation):
            render('Start 25:00.', plan(['25:00'], o=[[0, 'clock']]))
        bad = copy.deepcopy(TANK_PLAN)
        bad['answer'] = '09:44:10, 1500 kg'
        with self.assertRaises(GroundingViolation):
            render(TANK, bad)

    def test_legacy_proof_and_complete_markdown_fence_are_supported(self):
        content = legacy.proof(calculations=[{'expression': '7 * 6', 'result': '42'}])
        answer = validate_and_render(chr(96) * 3 + 'json\n' + content + '\n' + chr(96) * 3, '7 * 6', '7 * 6')
        self.assertIn('42', answer)

    def test_partial_fence_duplicate_json_and_nan_are_not_salvaged(self):
        for content in [chr(96) * 3 + 'json\n{"facts": []',
                        '{"v":2,"v":2,"q":[],"s":[],"o":[],"u":[]}',
                        '{"v":2,"q":[NaN],"s":[],"o":[],"u":[]}']:
            with self.subTest(content=content), self.assertRaises(GroundingViolation):
                validate_and_render(content, TANK, TANK)


class DirectCalculationFlowTests(unittest.TestCase):
    def helper(self):
        return legacy.DirectGroundingTests('test_fully_supplied_deterministic_derivation_is_allowed')

    def test_compact_plan_is_one_generation_without_research(self):
        for router in [True, False]:
            with self.subTest(router=router):
                answer, llm = self.helper().run_direct(TANK, [json.dumps(TANK_PLAN)], multi_model=router)
                self.assertIn('09:44:10', answer)
                self.assertIn('1500 kg', answer)
                self.assertEqual(len(llm.calls), 1)

    def test_recognized_structured_content_is_serialized_then_validated(self):
        class Provider:
            def analyze(self, **kwargs):
                return {'content': TANK_PLAN}
        result = analyze_direct(Provider())
        self.assertIsInstance(result['content'], str)
        self.assertIn('1500 kg', validate_and_render(result['content'], TANK, TANK))

    def test_repeated_invalid_proof_is_technical_failure_not_missing_data(self):
        with self.assertRaises(DirectProviderFailure) as caught:
            self.helper().run_direct(TANK, ['broken JSON', 'broken JSON'])
        error = caught.exception.public_error()
        self.assertEqual(error['code'], 'DIRECT_OUTPUT_INVALID')
        self.assertEqual(caught.exception.status_code, 502)
        self.assertNotIn('UNKNOWN', error['message'])
        self.assertNotIn('broken JSON', str(error))

    def test_repair_provider_failure_is_not_hidden_as_unknown(self):
        with self.assertRaises(DirectProviderFailure) as caught:
            self.helper().run_direct(TANK, ['broken JSON', RuntimeError('unsupported model')])
        self.assertEqual(caught.exception.failure_subtype, 'unsupported/deprecated')

    def test_genuine_missing_data_still_returns_named_unknown(self):
        answer, llm = self.helper().run_direct('3 boxes, weight per box missing.',
                                              [json.dumps(plan([], u=['weight per box']))])
        self.assertIn('UNKNOWN', answer)
        self.assertIn('weight per box', answer)
        self.assertEqual(len(llm.calls), 1)

    def test_truncation_is_repaired_even_if_prefix_is_valid_json(self):
        import hermes_agent.direct_answer_grounding as grounding
        provider = legacy.ScriptedLLM([json.dumps(TANK_PLAN)])
        answer = grounding.enforce_direct_answer(provider,
            {'content': json.dumps(plan([], u=['time'])), 'finish_reason': 'length'},
            source=TANK, goal=TANK)
        self.assertIn('09:44:10', answer)
        self.assertEqual(len(provider.calls), 1)


class DirectCalculationApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_plan_reaches_api_and_persistence(self):
        helper = api_fixture.DirectGroundingApiTests('test_valid_repair_preserves_fraction_and_missing_input_names')
        response, _ = await helper.send(TANK, [json.dumps(TANK_PLAN)])
        self.assertEqual(response.status_code, 200)
        self.assertIn('09:44:10', response.text)

    async def test_invalid_output_is_502_without_fake_answer_or_persistence(self):
        helper = api_fixture.DirectGroundingApiTests('test_valid_repair_preserves_fraction_and_missing_input_names')
        response, _ = await helper.send(TANK, ['broken JSON', 'broken JSON'])
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['error']['code'], 'DIRECT_OUTPUT_INVALID')
        self.assertNotIn('choices', response.json())
        self.assertNotIn('research', response.json())


if __name__ == '__main__':
    unittest.main()
