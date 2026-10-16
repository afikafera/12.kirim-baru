"""Offline API integration of DIRECT grounding with scripted model output."""
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import FastAPI, Request
from hermes_agent.direct_provider_recovery import DirectProviderFailure
import test_direct_answer_grounding as grounding
import test_research_api_contract as fixture

api = fixture.api_main


class DirectGroundingApiTests(unittest.IsolatedAsyncioTestCase):
    async def send(self, question, outputs):
        app = FastAPI()
        app.add_exception_handler(DirectProviderFailure, api.direct_provider_failure_handler)
        helper = grounding.DirectGroundingTests('test_exact_captured_train_output_cannot_escape')
        runs = []

        @app.post('/chat/completions')
        async def chat(body: dict, request: Request):
            request.state.user_id = 'offline-grounding-test'
            return await api.chat_completions(body, request)

        def direct(query, **kwargs):
            answer, llm = helper.run_direct(query, outputs, context=kwargs.get('context', ''),
                                             attachments=kwargs.get('attachments'))
            runs.append(llm)
            return answer

        with patch.object(api.aran, 'research', side_effect=direct), \
             patch.object(api.mm, 'persist_chat_exchange', return_value={'id': 'offline-conversation'}) as persist, \
             patch('langfuse.get_client', return_value=SimpleNamespace(
                 start_as_current_observation=lambda **_: nullcontext())):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://offline') as client:
                response = await client.post('/chat/completions', json={
                    'model': '9routerpc', 'messages': [{'role': 'user', 'content': question}],
                })
            if response.status_code == 200:
                self.assertEqual(persist.call_count, 1)
                self.assertEqual(persist.call_args.kwargs['assistant_content'],
                                 response.json()['choices'][0]['message']['content'])
            else:
                persist.assert_not_called()
        return response, runs

    async def test_captured_fabrication_cannot_reach_api_or_persistence(self):
        response, runs = await self.send(grounding.CAPTURE['query'],
                                        [grounding.CAPTURE['answer'], grounding.CAPTURE['answer']])
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['error']['code'], 'DIRECT_OUTPUT_INVALID')
        self.assertNotIn('choices', response.json())
        self.assertNotRegex(response.text, r'\b[48]\s+roda|\b2\s+gerbong')
        self.assertEqual(runs, [])

    async def test_valid_repair_preserves_fraction_and_missing_input_names(self):
        repair = grounding.proof(calculations=[
            {'expression': 'half(100 - 20 + 15) + pair(5)', 'result': '57.5'}
        ], unknowns=['jumlah gerbong aktual', 'jumlah roda per gerbong'])
        response, _ = await self.send(grounding.CAPTURE['query'], [grounding.CAPTURE['answer'], repair])
        self.assertEqual(response.status_code, 200)
        answer = response.json()['choices'][0]['message']['content']
        self.assertIn('57.5', answer)
        self.assertIn('tidak konsisten', answer)
        self.assertIn('jumlah gerbong aktual', answer)
        self.assertIn('jumlah roda per gerbong', answer)

    async def test_generic_missing_parameter_has_200_unknown(self):
        response, _ = await self.send('3 boxes, total weight? weight per box not given',
                                      [grounding.proof(unknowns=['weight per box'])])
        self.assertEqual(response.status_code, 200)
        self.assertIn('UNKNOWN', response.json()['choices'][0]['message']['content'])

    async def test_initial_provider_failure_retains_structured_error(self):
        response, _ = await self.send('3 boxes, total weight? weight per box not given',
                                      [RuntimeError('unsupported model')])
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['error']['route'], 'DIRECT')
        self.assertNotIn('choices', response.json())


if __name__ == '__main__':
    unittest.main()
