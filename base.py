from pydantic import BaseModel, validator
from typing import NamedTuple, Optional, Literal
import json


class WithdrawRequest(BaseModel):
    """
    Lnurlw withdraw transaction object
    """
    userid: str
    k1: str

    clearnet_url: str
    lnurlw: str
    lnurl: str

    redeemed: bool = False
    status: Literal["CREATED", "VERIFIED", "REJECTED", "QUEUED", "PAID", "PAYMENT_FAILED"]
    reason: Optional[str] = None

    max_withdrawable: Optional[int] = None
    min_withdrawable: Optional[int] = None

    payment_hash: Optional[str] = None
    bolt11: Optional[str] = None
    invoice_amt: Optional[str] = None
    invoice_addr: Optional[str] = None

    ts_created: Optional[int] = None   # timestamps
    ts_invoice: Optional[int] = None
    ts_paid: Optional[int] = None


class LNDInvoice(BaseModel):
    """
    Decoded invoice
    """
    payment_hash: str
    bolt11: Optional[str] = None
    preimage: Optional[str] = None
    state: Optional[str] = None
    destination: str
    num_satoshis: int
    timestamp: str
    expiry: str
    description: str
    description_hash: str
    fallback_addr: str
    cltv_expiry: str
    route_hints: list
    payment_addr: str
    features: dict

    @validator("features")
    def convert_dict_to_json(cls, value):
        return json.dumps(value)
    
    @validator("route_hints")
    def convert_list_to_json(cls, value):
        return json.dumps(value)


class LNPayment(BaseModel):
    payment_hash: str
    userid: str
    payment_preimage: str
    value_sat: int
    status: Literal["IN_FLIGHT", "SUCCEEDED", "FAILED", "INITIATED"]
    fee_sat: int
    ts_create: str
    failure_reason: str


class DepositRequest(BaseModel):
    userid: str
    payment_hash: str
    status: Literal["CREATED", "PAID", "SETTLED", "PAYMENT_FAILED"]
    amount: Optional[str]
    ts_created: Optional[int]


class TokenData(BaseModel):
    token: str
    userid: str


class StatusResponse(NamedTuple):
    error_message: Optional[str]
    balance_msat: int


class InvoiceResponse(NamedTuple):
    # LND invoice create response
    ok: bool
    payment_hash: Optional[str] = None  # payment_hash, rpc_id
    payment_request: Optional[str] = None   # bolt11
    error_message: Optional[str] = None


class PaymentResponse(NamedTuple):
    # when ok is None it means we don't know if this succeeded
    ok: Optional[bool] = None
    payment_hash: Optional[str] = None  # payment_hash, rcp_id
    fee_msat: Optional[int] = None
    preimage: Optional[str] = None
    error_message: Optional[str] = None


class PaymentStatus(NamedTuple):
    payment_hash: str
    payment_preimage: str
    value_sat: int
    status: str
    fee_sat: int
