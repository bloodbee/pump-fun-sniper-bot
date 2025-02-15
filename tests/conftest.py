import pytest
import json

from solders.litesvm import LiteSVM
from solders.keypair import Keypair


@pytest.fixture
def load_json():
    """Fixture to load JSON data from a given file path."""

    def _load_json(filepath):
        with open(filepath, "r") as f:
            return json.load(f)

    return _load_json


@pytest.fixture
def load_file():
    """Fixture to load JSON data from a given file path."""

    def _load_file(filepath):
        with open(filepath, "r") as f:
            return f.read()

    return _load_file


@pytest.fixture
def mock_token_storage():
    """Fixture to mock the token storage with some example tokens."""
    return [
        {"name": "Trump Official Memecoin", "address": "token_1"},
        {"name": "Doge Classic", "address": "token_2"},
        {"name": "Ethereum Killer", "address": "token_3"},
        {"name": "Trump Win All", "address": "token_4"},
    ]


@pytest.fixture
def valid_token():
    """Fixture for a valid token that should be bought."""
    return {
        "name": "BARRON",
        "symbol": "BARRON",
        "description": "$Barron is being coronation!",
        "image": "https://cf-ipfs.com/ipfs/QmNLoZLoo47z4QcBKWPXYJEL7LX38Fu6EcqH5f2P8cAURv",
        "decimals": 6,
        "address": "9QUYvUGiqCALxrMCyJrVYXtJSpt4BYzPRv5ZRjsdqzkh",
        "mint_authority": "",
        "freeze_authority": "",
        "current_supply": 965838274.841946,
        "extensions": [],
    }


@pytest.fixture
def valid_token_mint_revoked():
    """Fixture for a valid token that should be bought."""
    return {
        "name": "BARRON",
        "symbol": "BARRON",
        "description": "$Barron is being coronation!",
        "image": "https://cf-ipfs.com/ipfs/QmNLoZLoo47z4QcBKWPXYJEL7LX38Fu6EcqH5f2P8cAURv",
        "decimals": 6,
        "address": "9QUYvUGiqCALxrMCyJrVYXtJSpt4BYzPRv5ZRjsdqzkh",
        "mint_authority": "gBUYvUGiqCALxrMCyJrVYXtJSpt4BYzPRv5ZRjsdqzkh",
        "freeze_authority": "",
        "current_supply": 965838274.841946,
        "extensions": [],
    }


@pytest.fixture
def valid_token_freeze_revoked():
    """Fixture for a valid token that should be bought."""
    return {
        "name": "BARRON",
        "symbol": "BARRON",
        "description": "$Barron is being coronation!",
        "image": "https://cf-ipfs.com/ipfs/QmNLoZLoo47z4QcBKWPXYJEL7LX38Fu6EcqH5f2P8cAURv",
        "decimals": 6,
        "address": "9QUYvUGiqCALxrMCyJrVYXtJSpt4BYzPRv5ZRjsdqzkh",
        "mint_authority": "",
        "freeze_authority": "AdUYvUGiqCALxrMCyJrVYXtJSpt4BYzPRv5ZRjsdqzkh",
        "current_supply": 965838274.841946,
        "extensions": [],
    }


@pytest.fixture
def litesvm_client():
    """Fixture to create a LiteSVM Solana simulator."""
    client = LiteSVM()
    return client


@pytest.fixture
def test_account(litesvm_client):
    """Fixture to create and fund a test account."""
    account = Keypair()
    litesvm_client.airdrop(account.pubkey(), 1_000_000_000)  # 1 SOL
    return account
