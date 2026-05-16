"""Pytest test suite for omrt_extractor.

Live API calls are forbidden in tests (CLAUDE.md rule). Use respx for
httpx mocking and pytest-mock for general mocking.

The test_schemas.py file is the schema contract. All 36 tests should
always pass.
"""
