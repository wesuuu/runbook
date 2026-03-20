"""Tests for app.core.deps.get_or_404 utility."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.deps import get_or_404


@pytest.fixture
def mock_db():
    return AsyncMock()


@patch("app.core.deps.select")
async def test_get_or_404_returns_record(mock_select, mock_db):
    record = MagicMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = record
    mock_db.execute.return_value = result_mock

    model = MagicMock(__name__="Widget")
    got = await get_or_404(mock_db, model, uuid.uuid4())
    assert got is record
    mock_select.assert_called_once_with(model)


@patch("app.core.deps.select")
async def test_get_or_404_raises_404_default_message(mock_select, mock_db):
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = result_mock

    model = MagicMock(__name__="Widget")

    with pytest.raises(HTTPException) as exc_info:
        await get_or_404(mock_db, model, uuid.uuid4())

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Widget not found"


@patch("app.core.deps.select")
async def test_get_or_404_raises_404_custom_message(mock_select, mock_db):
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = result_mock

    model = MagicMock(__name__="Widget")

    with pytest.raises(HTTPException) as exc_info:
        await get_or_404(mock_db, model, uuid.uuid4(), detail="Nope")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Nope"


@patch("app.core.deps.select")
async def test_get_or_404_applies_options(mock_select, mock_db):
    record = MagicMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = record
    mock_db.execute.return_value = result_mock

    model = MagicMock(__name__="Widget")
    fake_option = MagicMock()
    stmt = mock_select.return_value.where.return_value

    got = await get_or_404(
        mock_db, model, uuid.uuid4(), options=[fake_option]
    )
    assert got is record
    stmt.options.assert_called_once_with(fake_option)
