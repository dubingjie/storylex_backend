import unittest
from types import SimpleNamespace
from openai import APIConnectionError, APIStatusError, APITimeoutError
from utils.model_errors import model_error


class ModelErrorTests(unittest.TestCase):
    def test_provider_status_codes_are_specific_and_redacted(self):
        for status, expected in [(401,'MODEL_AUTH_FAILED'),(402,'MODEL_QUOTA_EXHAUSTED'),
                                 (403,'MODEL_ACCESS_DENIED'),(404,'MODEL_NOT_FOUND'),
                                 (429,'MODEL_RATE_LIMITED'),(503,'MODEL_SERVICE_ERROR')]:
            response=SimpleNamespace(status_code=status,request=object(),headers={})
            exc=APIStatusError('secret-key-provider-body',response=response,body={'error':'secret-key'})
            result=model_error(exc)
            self.assertEqual(result['error_code'],expected)
            self.assertEqual(result['http_status'],status)
            self.assertNotIn('secret',str(result))

    def test_timeout_connection_and_unknown(self):
        self.assertEqual(model_error(APITimeoutError(request=object()))['error_code'],'MODEL_TIMEOUT')
        self.assertEqual(model_error(APIConnectionError(request=object()))['error_code'],'MODEL_CONNECTION_FAILED')
        self.assertEqual(model_error(RuntimeError('secret-key'))['error_code'],'MODEL_CALL_FAILED')
        self.assertNotIn('secret',str(model_error(RuntimeError('secret-key'))))
