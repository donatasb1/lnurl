import asyncio
from typing import List
from .node import LndRestNode
from .crud import PSQLClient
import logging

logging.basicConfig(filename='app.log', encoding='utf-8', level=logging.DEBUG, format='%(asctime)s %(message)s')

tasks: List[asyncio.Task] = []

async def process_payment_notifications(node: LndRestNode, psql: PSQLClient):
    async for status in node.track_payments():
        if status.status == "SUCCEEDED":
            await psql.finalize_payment(status)
        elif status.status == "FAILED":
            await psql.failed_payment(status)

async def process_invoice_notifications(node: LndRestNode, psql: PSQLClient): 
    async for invoice in node.paid_invoices_stream():
        if invoice.state == "SETTLED":
            await psql.deposit_finalize(invoice)
    

def create_task(coro):
    task = asyncio.create_task(coro)
    tasks.append(task)
    return task


def create_permanent_task(func, *args):
    return create_task(catch_everything_and_restart(func, *args))


def cancel_all_tasks():
    for task in tasks:
        try:
            task.cancel()
        except Exception as exc:
            logging.warning(f"error while cancelling task: {str(exc)}")


async def catch_everything_and_restart(func, *args):
    try:
        await func(*args)
    except (asyncio.CancelledError, KeyboardInterrupt):
        print('STOPPING background services...')
        raise  # because we must pass this up
    except Exception as exc:
        logging.error("caught exception in background task:", exc)
        logging.error("Restarting in 5 seconds...")
        await asyncio.sleep(5)
        await catch_everything_and_restart(func, *args)