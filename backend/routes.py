import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field, field_validator

from . import ledger, pipeline


router = APIRouter(prefix="/api")


class TextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)

    @field_validator("text")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must not be blank")
        return value


class CustomerIdRequest(BaseModel):
    customer_id: int = Field(gt=0)


def _pending_response(
    result: dict[str, Any],
) -> dict[str, Any]:
    status_codes = {
        "not_found": 404,
        "expired": 410,
        "already_confirmed": 409,
        "confirmation_in_progress": 409,
        "cancelled": 409,
        "customer_required": 409,
        "amount_required": 409,
        "invalid_customer_selection": 422,
    }
    if result.get("status") == "retryable_error":
        raise HTTPException(
            status_code=503,
            detail=result,
            headers={"Retry-After": "1"},
        )
    status_code = status_codes.get(result.get("status"))
    if status_code is not None:
        raise HTTPException(status_code=status_code, detail=result)
    return result


@router.post("/text")
def submit_text(request: TextRequest) -> dict[str, Any]:
    try:
        result = pipeline.handle_text(request.text)
    except RuntimeError as error:
        raise HTTPException(
            status_code=502,
            detail="Transaction extraction service failed",
        ) from error
    if result.get("status") == "invalid_input":
        raise HTTPException(status_code=422, detail=result)
    if result.get("status") == "invalid_extraction":
        raise HTTPException(status_code=502, detail=result)
    return result


@router.post("/confirm/{pending_id}")
def confirm(
    pending_id: int = Path(gt=0),
) -> dict[str, Any]:
    try:
        result = pipeline.confirm_pending(pending_id)
    except sqlite3.OperationalError as error:
        message = str(error).lower()
        if "locked" in message or "busy" in message:
            raise HTTPException(
                status_code=503,
                detail={
                    "status": "retryable_error",
                    "pending_id": pending_id,
                    "retryable": True,
                },
                headers={"Retry-After": "1"},
            ) from error
        raise

    if result.get("status") != "confirmed":
        return _pending_response(result)

    return result


@router.post("/pending/{pending_id}/customer")
def choose_pending_customer(
    request: CustomerIdRequest,
    pending_id: int = Path(gt=0),
) -> dict[str, Any]:
    try:
        result = pipeline.select_pending_customer(pending_id, request.customer_id)
    except sqlite3.OperationalError as error:
        message = str(error).lower()
        if "locked" in message or "busy" in message:
            raise HTTPException(
                status_code=503,
                detail={
                    "status": "retryable_error",
                    "pending_id": pending_id,
                    "retryable": True,
                },
                headers={"Retry-After": "1"},
            ) from error
        raise
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return _pending_response(result)


@router.post("/cancel/{pending_id}")
def cancel(
    pending_id: int = Path(gt=0),
) -> dict[str, Any]:
    try:
        result = pipeline.cancel_pending(pending_id)
    except sqlite3.OperationalError as error:
        message = str(error).lower()
        if "locked" in message or "busy" in message:
            raise HTTPException(
                status_code=503,
                detail={
                    "status": "retryable_error",
                    "pending_id": pending_id,
                    "retryable": True,
                },
                headers={"Retry-After": "1"},
            ) from error
        raise
    if result.get("status") == "cancelled":
        return result
    return _pending_response(result)


@router.post("/undo")
def undo(request: CustomerIdRequest) -> dict[str, Any]:
    try:
        transaction_id = ledger.void_last(request.customer_id)
    except ValueError as error:
        message = str(error)
        if message.startswith("Unknown customer ID:"):
            raise HTTPException(status_code=404, detail=message) from error
        raise HTTPException(status_code=409, detail=message) from error
    return {
        "status": "voided",
        "transaction_id": transaction_id,
        "balance": ledger.get_balance(request.customer_id),
        "transaction": ledger.get_transaction(transaction_id),
    }


@router.get("/customers")
def customers() -> dict[str, Any]:
    return {"customers": ledger.list_customers()}


@router.get("/customers/{customer_id}/ledger")
def customer_ledger(customer_id: int = Path(gt=0)) -> dict[str, Any]:
    try:
        transactions = ledger.get_customer_ledger(customer_id)
        balance = ledger.get_balance(customer_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {
        "customer_id": customer_id,
        "transactions": transactions,
        "balance": balance,
    }


@router.get("/summary/today")
def today_summary() -> dict[str, int]:
    return ledger.daily_summary()
