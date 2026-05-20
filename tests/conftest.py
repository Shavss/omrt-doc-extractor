"""Pytest configuration — load .env so live-API tests pick up ANTHROPIC_API_KEY."""

from dotenv import load_dotenv

load_dotenv()
