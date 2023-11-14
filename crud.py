from .base import LNDInvoice, WithdrawRequest, LNPayment, PaymentStatus, DepositRequest
from datetime import datetime
import asyncio
import psycopg_pool
import psycopg
from psycopg.rows import dict_row


def lock_function(func):
    async def wrapper(*args, **kwargs):
        async with asyncio.Lock():
            return await func(*args, **kwargs)
    return wrapper


class PSQLClient:

    def __init__(self, conninfo):
        self.pool = psycopg_pool.AsyncConnectionPool(conninfo=conninfo)

    async def execute(self, q: str, *args):
        async with self.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(q, args)

    async def fetchone(self, q: str, *args) -> dict:
        async with self.pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                print("ARGS", args)
                await cur.execute(q, args)
                row = await cur.fetchone()
                return row
    
    async def fetchmany(self, q: str, *args) -> list[dict]:
        async with self.pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(q, args)
                rows = await cur.fetchall()
                return rows

    """
    WITHDRAW
    """

    async def create_withdraw_request(self, request: WithdrawRequest) -> None:
        q = """
        INSERT INTO withdraw_requests 
            (
                userid, k1, clearnet_url, lnurlw, lnurl, status, ts_created
            )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        return await self.execute(q, *request.model_dump(exclude_none=True, exclude={"redeemed"}).values())


    async def get_withdraw_request(self, k1) -> WithdrawRequest:
        q = """
        SELECT * 
        FROM withdraw_requests
        WHERE k1 = %s
        """
        row = await self.fetchone(q, k1)
        if row is not None:
            return WithdrawRequest(**row)


    async def get_pending_requests(self, userid: str) -> int:
        q = """
        SELECT COUNT(k1) as pending
        FROM withdraw_requests
        WHERE userid = %s
        AND status NOT IN ('PAID', 'SETTLED', 'REJECTED', 'PAYMENT_FAILED')
        AND ts_created > %s
        """
        ts = int(datetime.utcnow().timestamp() - 60*5)
        count_requests = await self.fetchone(q, userid, ts)
        return count_requests.get("pending", 0)

    async def withdraw_bad_invoice(self, k1: str, invoice: LNDInvoice, reason: str = ""):
        q = """
        UPDATE withdraw_requests
        SET redeemed = %s,
        payment_hash = %s,
        ts_invoice = %s,
        amount = %s,
        destination = %s,
        status = 'REJECTED',
        reason = %s
        WHERE k1 = %s
        """
        current_time = int(datetime.utcnow().timestamp())
        return await self.execute(q, True, invoice.payment_hash, current_time, invoice.num_satoshis, invoice.destination, reason, k1)


    @lock_function
    async def withdraw_redeem_request(self, k1: str, invoice: LNDInvoice):
        q1 = """
        SELECT *
        FROM withdraw_requests
        WHERE k1 = %s
        AND status = 'VERIFIED'
        """
        q2 = f"""
        UPDATE withdraw_requests
        SET redeemed = {True},
        payment_hash = %s,
        bolt11 = %s,
        ts_invoice = %s,
        amount = %s,
        destination = %s,
        status = 'QUEUED'
        WHERE k1 = %s
        """
        q3 = """
        UPDATE balances
        SET amount = balances.amount -%s
        FROM withdraw_requests
        WHERE balances.userid = withdraw_requests.userid
        AND withdraw_requests.k1 = %s
        """
        q4 = """
        INSERT INTO locked_balances(payment_hash, amount)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
        """
        current_time = int(datetime.utcnow().timestamp())
        async with self.pool.connection() as conn:
            await conn.set_autocommit(True)
            async with conn.cursor(row_factory=dict_row) as cur:
                cur: psycopg.Cursor
                await cur.execute(q1, (k1, ))
                request = await cur.fetchone()
                if request is None:
                    return None
                async with conn.transaction():
                    await cur.execute(q2, (invoice.payment_hash, invoice.bolt11, current_time, invoice.num_satoshis, invoice.destination, k1))
                    await cur.execute(q3, (invoice.num_satoshis, k1))
                    await cur.execute(q4, (invoice.payment_hash, invoice.num_satoshis))
                await self.register_invoice(invoice)
                await self.create_payment(request, invoice)                
        # asyncio.create_task(self.register_invoice(invoice))
        # asyncio.create_task(self.create_payment(request, invoice))
        return WithdrawRequest(**request)


    async def register_invoice(self, invoice: LNDInvoice) -> None:
        q = """
        INSERT INTO withdraw_invoices
            (
                payment_hash, bolt11, state, destination, num_satoshis, timestamp, expiry, description,
                description_hash, fallback_addr, cltv_expiry, route_hints, payment_addr, features
            )
        VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        print("MODEL DUMP", invoice.model_dump(exclude={"preimage"}))
        return await self.execute(q, *invoice.model_dump(exclude={"preimage"}).values())


    async def update_withdraw_status(self, status: str, k1: str = None, hash: str = None, reason: str = "") -> None:
        if hash is not None:
            q = f"""
            UPDATE withdraw_requests
            SET status = %s,
            reason = %s
            WHERE payment_hash = '{hash}'
            """
        elif k1 is not None:
            q = f"""
            UPDATE withdraw_requests
            SET status = %s,
            reason = %s
            WHERE k1 = '{k1}'
            """
        return await self.execute(q, status, reason)
    
    async def create_withdraw_transaction(self, request: WithdrawRequest):
        q = """
        INSERT INTO withdraw_transactions (userid, payment_hash, amount)
        VALUES (%s, %s, %s)
        ON CONFLICT DO NOTHING
        """
        return await self.execute(request.userid, request.payment_hash, request.invoice_amt)

    async def create_payment(self, request: dict, invoice: LNDInvoice):
        q = """
        INSERT INTO withdraw_payments (payment_hash, userid, value_sat, ts_create)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """
        current_time = int(datetime.utcnow().timestamp())
        return await self.execute(q, invoice.payment_hash, request["userid"], invoice.num_satoshis, current_time)


    async def remove_from_lock(self, payment_hash: str):
        q = """
        DELETE FROM locked_balances
        WHERE payment_hash = %s
        """
        return await self.execute(q, payment_hash)
    

    async def finalize_payment(self, payment: LNPayment):
        q = """
        UPDATE withdraw_payments
        SET preimage = %s,
        fee_sat = %s,
        status = %s
        WHERE payment_hash = %s
        """
        q2 = """
        DELETE FROM locked_balances
        WHERE payment_hash = %s
        """
        q3 = """
        INSERT INTO withdraw_transactions (payment_hash, userid, amount, ts_create)
        SELECT %s, userid, %s, %s
        FROM withdraw_requests
        WHERE payment_hash = %s
        """
        q4 = """
        UPDATE withdraw_requests
        SET status = 'PAID'
        WHERE payment_hash = %s
        """
        q5 = """
        UPDATE withdraw_invoices
        SET preimage = %s
        WHERE payment_hash = %s
        """
        current_time = int(datetime.utcnow().timestamp())
        async with self.pool.connection() as conn:
            await conn.set_autocommit(True)
            async with conn.cursor(row_factory=dict_row) as cur:
                async with conn.transaction():
                    await cur.execute(q, (payment.payment_preimage, payment.fee_sat, payment.status, payment.payment_hash))
                    await cur.execute(q2, (payment.payment_hash, ))
                    await cur.execute(q3, (payment.payment_hash, payment.value_sat, current_time, payment.payment_hash))
                await cur.execute(q4, (payment.payment_hash, ))
                await cur.execute(q5, (payment.payment_preimage, payment.payment_hash))
                return

    async def failed_payment(self, payment: PaymentStatus):
        q = """
        UPDATE withdraw_payments
        SET status = "FAILED"
        WHERE payment_hash = %s
        """
        self.update_withdraw_status(hash=payment.payment_hash, status="PAYMENT_FAILED")
        return await self.execute(q, payment.payment_hash)
    
    """
    DEPOSIT
    """

    async def get_user_by_k1(self, k1: str):
        q = """
        SELECT userid
        FROM users
        WHERE k1 = %s
        """
        return await self.execute(q, k1)
    
    async def deposit_request_create(self, request: DepositRequest, invoice: LNDInvoice):
        q = """
        INSERT INTO deposit_requests(userid, payment_hash, status, ts_created)
        VALUES (%s, %s, %s, %s)
        """
        await self.deposit_invoice_create(invoice)
        return await self.execute(q, request.userid, request.payment_hash, request.status, request.ts_created)

    async def deposit_invoice_create(self, invoice: LNDInvoice):
        q = """
        INSERT INTO deposit_invoices
        (
            payment_hash, bolt11, destination, num_satoshis, timestamp, expiry, description,
            description_hash, fallback_addr, cltv_expiry, route_hints, payment_addr, features
        )
        VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        return await self.execute(q, invoice.model_dump().values())
    
    async def deposit_create_transaction(self, invoice: LNDInvoice):
        q = """
        INSERT INTO deposit_transactions(userid, payment_hash, amount, ts_create)
        VALUES (%s, %s, %s, %s)
        """
        return await self.execute(q, invoice)
    
    async def deposit_finalize(self, invoice: LNDInvoice):
        q = """
        UPDATE deposit_invoices
        SET state = %s
        WHERE payment_hash = %s
        """
        q2 = """
        INSERT INTO deposit_transactions(userid, payment_hash, amount, ts_create)
        SELECT userid, %s, %s, %s
        FROM deposit_requests
        WHERE payment_hash = %s
        """
        q3 = """
        UPDATE balances
        SET amount = balances.amount + %s
        FROM deposit_requests
        WHERE balances.userid = deposit_requests.userid
        AND deposit_requests.payment_hash = %s;
        """
        q4 = """
        UPDATE deposit_requests
        SET status = "SETTLED"
        WHERE payment_hash = %s
        """
        current_time = int(datetime.utcnow().timestamp())
        async with self.pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                async with conn.transaction():
                    await cur.execute(q, (invoice.state, invoice.payment_hash))
                    await cur.execute(q2, (invoice.payment_hash, invoice.num_satoshis, current_time, invoice.payment_hash))
                    await cur.execute(q3, (invoice.num_satoshis, invoice.payment_hash))
                    await cur.execute(q3, (invoice.num_satoshis, invoice.payment_hash,))
                return