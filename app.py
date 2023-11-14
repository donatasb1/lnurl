from .node import LndRestNode
from .base import TokenData, WithdrawRequest, DepositRequest
from .crud import PSQLClient
from .helpers import decode_access_token, RateLimiter, random_k1
from .lnurl import LnurlPayResponse, PayRequestMetadata, LnurlPayActionResponse, MessageAction, encode, LnurlErrorResponse, LnurlSuccessResponse, LnurlWithdrawResponse, CreateLnurlResponse
from .db import create_tables
from .tasks import create_permanent_task, process_invoice_notifications, process_payment_notifications, cancel_all_tasks
from redis import Redis, ConnectionPool
import asyncio
from fastapi import FastAPI, Depends, HTTPException, Query, BackgroundTasks
from typing import Annotated
from datetime import datetime
from contextlib import asynccontextmanager
import os

psql_coninf = os.getenv("POSTGRES_CONINFO")

r_host = os.getenv("REDIS_HOST")
r_port = os.getenv("REDIS_PORT")
r_psq = os.getenv("REDIS_PSW")


MIN_AVAIL = 50000
FEE_LIMIT_SAT = 10000

SCHEMA = "https://"
DOMAIN = "fancy.domain"


redis_pool = ConnectionPool(host=r_host,
                            port=r_port,
                            password=r_psw,
                            db=0, decode_responses=True)

async def get_redis_connection():
    connection = Redis(connection_pool=redis_pool)
    yield connection


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    create_permanent_task(process_invoice_notifications, node, psql)
    create_permanent_task(process_payment_notifications, node, psql)
    yield
    cancel_all_tasks()

node = LndRestNode()
psql = PSQLClient(psql_coninf)
app = FastAPI(lifespan=lifespan)
limiter = RateLimiter(interval=60)


@app.get("/withdraw/ln/request")
async def ln_withdraw_request(
    token_data:  Annotated[TokenData, Depends(decode_access_token)],
    redis_conn: Redis = Depends(get_redis_connection)):
    """
    Create withdraw request - private lnurlw link.
    Time limit user requests. Ensure single pending withdraw request exists per user.
    """
    if token_data is None:
        raise HTTPException(status_code=400, detail="Invalid token")
    
    # one request per 5minutes for user
    is_limited = await limiter.register(token_data.userid)
    if is_limited:
        raise HTTPException(status_code=400, detail="Please try in a few minutes")
    
    # verify balance
    available = redis_conn.hget(f"{token_data.userid}::session", "balance")
    if available is None:
        raise HTTPException(status_code=400, detail="Invalid token")
    available = int(available)
    if available < MIN_AVAIL:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    pending = await psql.get_pending_requests(token_data.userid)
    if pending > 0:
        # TODO: replace error
        raise HTTPException(status_code=400, detail="User has pending requests")
    
    # create withdraw hash
    random_k1_value = random_k1()
    # create link from hash
    PATH = "/withdraw/ln/cb?k1="
    clearnet_url = SCHEMA+DOMAIN+PATH+random_k1_value
    lnurl_legacy = "lightning:"+encode(clearnet_url)
    lnurlw = "lnurlw://"+DOMAIN+PATH+random_k1_value

    req = WithdrawRequest(
        userid=token_data.userid,
        k1=random_k1_value,
        clearnet_url=clearnet_url,
        lnurl=lnurl_legacy,
        lnurlw=lnurlw,
        status="CREATED",
        ts_created=int(datetime.utcnow().timestamp()),
    )

    # register request
    await psql.create_withdraw_request(req)
    redis_conn.set(random_k1_value, value=token_data.userid, ex=600)

    # decide if need extra verification
    # and decide whether to return lnurl here or somewhere else
    return CreateLnurlResponse(lnurl=lnurl_legacy, lnurlw=lnurlw)


@app.get("/withdraw/ln/cb")
async def lnurlw_callback(
    k1: str,
    redis_conn: Redis =Depends(get_redis_connection)
    ) -> LnurlWithdrawResponse | LnurlErrorResponse:
    """
    Handle call to generated lnurlw
    Broadcast min/max available amount
    """
    # request valid for 10 minutes
    exists = redis_conn.exists(k1)
    if exists == 0:
        return LnurlErrorResponse(reason="Request expired")    
    # get WithdrawRequest from db
    # does not matter how many times respond to this
    request = await psql.get_withdraw_request(k1)
    if not (request is not None and request.status == "CREATED"):
        return LnurlErrorResponse(reason="Invalid withdraw request")
    request: WithdrawRequest

    balance = redis_conn.hget(f"{request.userid}::session", "balance")
    if balance is None:
        return LnurlErrorResponse(reason="Session not found")
    balance = int(balance)
    if balance < MIN_AVAIL:
        return LnurlErrorResponse(reason="Insufficient balance. Min amount: "+ MIN_AVAIL)
    
    PATH  = "/withdraw"
    callback = SCHEMA + DOMAIN + PATH
    descr = "Some withdraw description"

    await psql.update_withdraw_status(k1=k1, status="VERIFIED")
    
    return LnurlWithdrawResponse(
        callback=callback,
        k1=k1,
        maxWithdrawable=balance,
        minWithdrawable=50000,
        defaultDescription=descr,
    )


@app.get("/withdraw/ln")
async def ln_withdraw(
    k1: Annotated[str, Query(max_length=64, min_length=64)],
    pr: str,
    background_tasks: BackgroundTasks,
    redis_conn: Redis = Depends(get_redis_connection),
    ) -> LnurlSuccessResponse | LnurlErrorResponse:

    userid = redis_conn.get(k1)
    if userid is None:
        return LnurlErrorResponse(reason="Request expired")
    
    # call node to decode invoice
    decoded_invoice = await node.decode_invoice(pr)
    if decoded_invoice is None:
        return LnurlErrorResponse(reason="Invoice decode error")    

    # lock from trading during processing
    redis_conn.hset(f"{userid}::session", "status", "locked")
    background_tasks.add_task(redis_conn.hset, f"{userid}::session", "status", "active")

    available_balance = redis_conn.hget(f"{userid}::session", "balance")
    if available_balance is None:
        # register rejected invoice anyway
        await psql.withdraw_bad_invoice(k1, decoded_invoice, "No session")
        return LnurlErrorResponse(reason="Authentication error")
    available_balance = int(available_balance)
    if (decoded_invoice.num_satoshis > available_balance) | (decoded_invoice.num_satoshis < MIN_AVAIL):
        # register rejected invoice anyway
        await psql.withdraw_bad_invoice(k1, decoded_invoice, "Insufficient balance")
        return LnurlErrorResponse(reason="Insufficient balance")
    
    # one chance to submit valid amount
    request = await psql.withdraw_redeem_request(k1, decoded_invoice)
    if request is None:
        return LnurlErrorResponse(reason="Invalid request")
    
    # pay async
    asyncio.create_task(node.pay_invoice(decoded_invoice.bolt11, FEE_LIMIT_SAT))

    return LnurlSuccessResponse()

@app.get("/deposit/ln/request")
async def create_deposit_request(
    token_data: Annotated[TokenData, Depends(decode_access_token)],
    redis_conn: Redis = Depends(get_redis_connection)
):
    if token_data is None:
        raise ValueError
    
    # create withdraw hash
    random_k1_value = random_k1()
    # create link from hash
    PATH = "/deposit/ln?k1="
    clearnet_url = SCHEMA+DOMAIN+PATH+random_k1_value
    lnurl_legacy = encode(clearnet_url)
    lnurlp = "lnurlp://"+DOMAIN+PATH+random_k1_value

    req = DepositRequest(
        userid=token_data.userid,
        k1=random_k1_value,
        clearnet_url=clearnet_url,
        lnurl=lnurl_legacy,
        lnurlp=lnurlp,
        status="CREATED",
        ts_created=datetime.utcnow().timestamp(),
    )

    # register request
    await psql.create_withdraw_request(req)
    redis_conn.set(random_k1_value, value=token_data.userid, ex=600)

    # decide if need extra verification
    # and decide whether to return lnurl here or somewhere else
    return CreateLnurlResponse(lnurl=lnurl_legacy, lnurlw=lnurlp)

@app.get("/deposit/ln/cb")
async def lnurlp_callback(
    k1: str,
    ) -> LnurlWithdrawResponse | LnurlErrorResponse:
    """
    Handle call to generated lnurlw
    Broadcast min/max available amount
    """
    # get maxSendable, minSendable
    MIN_SENDABLE = 10000
    MAX_SENDABLE = 100000000
    # means user found q key in email
    # send wallet a response with min and max withdawable
    PATH = "/deposit?k1="
    callback = SCHEMA + DOMAIN + PATH + k1
    descr = "Some deposit description"

    return LnurlPayResponse(
        callback=callback,
        minSendable=MIN_SENDABLE,
        maxSendable=MAX_SENDABLE,
        metadata=PayRequestMetadata(text_plain=descr)
    )


@app.get("/deposit/ln")
async def ln_deposit(k1: str, amount: int = Query(gt=100000),
                     redis_conn: Redis = Depends(get_redis_connection)):
    
    # create invoice and corresponding deposit request
    # 

    userid = await psql.get_user_by_k1(k1)
    if userid is None:
        raise ValueError
    
    descr = "Deposit to "
    invoice = await node.create_invoice(amount, unhashed_description=descr)

    if invoice is None:
        return LnurlErrorResponse(reason="Error generating invoice")
    
    req = DepositRequest(
        userid=userid,
        payment_hash=invoice.payment_hash,
        status="CREATED",
        amount=amount,
        ts_created=datetime.utcnow().timestamp(),
    )

    await psql.deposit_request_create(req, invoice)

    return LnurlPayActionResponse(
        pr=invoice.bolt11,
        successAction=MessageAction(message="Thank you!"),
    )
