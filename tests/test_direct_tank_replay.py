"""Replay the actual tank responses without making provider requests."""
import json
import unittest
from pathlib import Path
import test_direct_answer_grounding as legacy
import test_direct_calculation_plans as plans
from hermes_agent.direct_provider_recovery import DirectProviderFailure

CAPTURE=json.loads((Path(__file__).parent/'fixtures'/'direct_tank_live_20261014.json').read_text())
QWEN=next(d['content'] for d in CAPTURE['drafts'] if 'qwen' in d['model'])
MISTRAL=next(d['content'] for d in CAPTURE['drafts'] if 'mistral' in d['model'])


class DirectTankCapturedTests(unittest.TestCase):
    def helper(self):
        return legacy.DirectGroundingTests('test_fully_supplied_deterministic_derivation_is_allowed')

    def test_captured_unknown_only_repair_is_not_proof_of_missing_data(self):
        with self.assertRaises(DirectProviderFailure) as caught:
            self.helper().run_direct(CAPTURE['question'], [MISTRAL,QWEN],multi_model=True)
        self.assertEqual(caught.exception.failure_class,'DIRECT_OUTPUT_INVALID')
        self.assertNotIn('UNKNOWN',caught.exception.public_error()['message'])

    def test_captured_truncation_can_repair_to_code_executed_plan(self):
        answer,llm=self.helper().run_direct(CAPTURE['question'],
            [MISTRAL,json.dumps(plans.TANK_PLAN)],multi_model=True)
        self.assertIn('09:44:10',answer)
        self.assertIn('1500 kg',answer)
        self.assertEqual(len(llm.calls),2)

    def test_v2_unknown_needs_evidence_of_missing_input(self):
        with self.assertRaises(DirectProviderFailure) as caught:
            self.helper().run_direct(CAPTURE['question'],
                [json.dumps(plans.plan([],u=['waktu isi tangki']))]*2)
        self.assertEqual(caught.exception.failure_class,'DIRECT_OUTPUT_INVALID')

    def test_genuine_missing_input_remains_named_unknown(self):
        answer,llm=self.helper().run_direct('3 boxes; weight per box is not given.',
            [json.dumps(plans.plan([],u=['weight per box']))])
        self.assertIn('UNKNOWN',answer)
        self.assertIn('weight per box',answer)
        self.assertEqual(len(llm.calls),1)

    def test_unrelated_units_are_not_a_calculation_fallback(self):
        with self.assertRaises(DirectProviderFailure):
            self.helper().run_direct('3 boxes; weight missing.',
                [json.dumps(plans.plan(['3 boxes'],o=[[0,'kg']]))]*2)


if __name__=='__main__':
    unittest.main()
