"""Manual Gemini embedding diagnostic utility; not part of the application."""

import json
import os

import google.generativeai as genai


def find_vector(value):
    if isinstance(value, list) and value and all(isinstance(item, (int, float)) for item in value):
        return value
    if isinstance(value, dict):
        for nested in value.values():
            vector = find_vector(nested)
            if vector:
                return vector
    if isinstance(value, list):
        for nested in value:
            vector = find_vector(nested)
            if vector:
                return vector
    return None


key = os.environ.get("GEMINI_API_KEY")
print("GEMINI key length:", len(key) if key else None)
genai.configure(api_key=key)

for model in ["gemini-embedding-001", "gemini-embed-001", "text-embedding-004"]:
    try:
        print("\nTrying model:", model)
        response = genai.embed_content(model=model, content=["hello world"])
        payload = response if isinstance(response, (dict, list)) else response.__dict__
        print("response_snippet:", json.dumps(payload)[:2000])
        vector = find_vector(payload)
        print("vector_len:", len(vector) if vector else None)
    except Exception as exc:
        print("error for", model, repr(exc))
