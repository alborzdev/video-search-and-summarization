import io
import json
import unittest
from unittest.mock import patch

import server


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class TextEmbeddingAdapterTests(unittest.TestCase):
    @patch("server.urlopen")
    def test_translates_cosmos_response_to_openai_embedding_contract(self, urlopen):
        urlopen.return_value = _Response(
            json.dumps(
                {
                    "data": [
                        {"embeddings": [0.1, 0.2], "text_input": "robot"},
                        {"embeddings": [0.3, 0.4], "text_input": "forklift"},
                    ]
                }
            ).encode()
        )

        result = server.generate_text_embeddings(
            {"input": ["robot", "forklift"], "input_type": "query"}
        )

        self.assertEqual(result["data"][0]["embedding"], [0.1, 0.2])
        self.assertEqual(result["data"][1]["index"], 1)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, server.COSMOS_EMBED_API_URL)
        self.assertEqual(
            json.loads(request.data),
            {"model": server.COSMOS_EMBED_MODEL, "text_input": ["robot", "forklift"]},
        )

    def test_rejects_empty_or_oversized_batches(self):
        for payload in ({"input": []}, {"input": [""]}, {"input": ["x"] * 51}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                server.generate_text_embeddings(payload)


if __name__ == "__main__":
    unittest.main()
