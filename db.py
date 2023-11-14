import psycopg


def create_tables(conninfo: str):
    conn = psycopg.connect(conninfo=conninfo,
                           autocommit=True)
    cursor = conn.cursor()
    create_users_table(cursor)
    create_balances_table(cursor)
    create_withdraw_requests_table(cursor)
    create_withdraw_invoices_table(cursor)
    create_withdraw_payments_table(cursor)
    create_withdraw_locked_table(cursor)
    create_withdraw_txs_table(cursor)
    create_deposit_requests_table(cursor)
    create_deposit_invoice_table(cursor)
    create_deposit_transactions_table(cursor)
    cursor.close()
    conn.close()


def create_withdraw_requests_table(cursor):
    q = """
    DROP TABLE IF EXISTS withdraw_requests;

    CREATE TABLE IF NOT EXISTS withdraw_requests
    (
        userid character varying(100) NOT NULL,
        k1 character(64) NOT NULL PRIMARY KEY,
        clearnet_url character varying(300) NOT NULL,
        lnurlw character varying(300) NOT NULL,
        lnurl character varying(300) NOT NULL,
        redeemed boolean DEFAULT FALSE,
        status character varying(20) NOT NULL, 
        reason character varying(300),
        max_withdrawable bigint,
        min_withdrawable bigint,

        payment_hash character(64),

        bolt11 character varying(1023),
        amount bigint,
        destination character(100),
        ts_created bigint,
        ts_invoice bigint,
        ts_paid bigint

    )
    """
    cursor.execute(q)

def create_withdraw_invoices_table(cursor):
    q = """
    DROP TABLE IF EXISTS withdraw_invoices;

    CREATE TABLE IF NOT EXISTS withdraw_invoices
    (
        payment_hash character(64) NOT NULL PRIMARY KEY,
        bolt11 character varying(1023) NOT NULL,
        state character varying(20) NOT NULL,
        preimage character (64),
        destination character varying (100) NOT NULL,
        num_satoshis bigint NOT NULL,
        timestamp bigint NOT NULL,
        expiry bigint NOT NULL,
        description character varying (1023),
        description_hash character varying (1023),
        fallback_addr character varying (100),
        cltv_expiry bigint,
        route_hints text,
        payment_addr character (44),
        features text
    )
    """
    cursor.execute(q)

def create_withdraw_payments_table(cursor):
    q = """
    DROP TABLE IF EXISTS withdraw_payments;

    CREATE TABLE IF NOT EXISTS withdraw_payments
    (
        payment_hash character(64) PRIMARY KEY NOT NULL,
        userid character varying (100) NOT NULL,
        preimage character (64),
        value_sat bigint,
        status character varying (20),
        fee_sat bigint,
        ts_create bigint NOT NULL,
        failure_reason text
    )
    """
    cursor.execute(q)

def create_deposit_requests_table(cursor):
    q = """
    DROP TABLE IF EXISTS deposit_requests;

    CREATE TABLE IF NOT EXISTS deposit_requests
    (
        userid character varying (100) NOT NULL,
        payment_hash character (64) PRIMARY KEY NOT NULL,
        status character varying (20),
        amount bigint,
        ts_created bigint NOT NULL
    )
    """
    cursor.execute(q)

def create_deposit_invoice_table(cursor):
    q = """
    DROP TABLE IF EXISTS deposit_invoices;

    CREATE TABLE IF NOT EXISTS deposit_invoices
    (
        payment_hash character(64) NOT NULL PRIMARY KEY,
        bolt11 character varying(1023) NOT NULL,
        state character varying(20) NOT NULL,
        preimage character (64),
        destination character varying (100) NOT NULL,
        num_satoshis bigint NOT NULL,
        timestamp bigint NOT NULL,
        expiry bigint NOT NULL,
        description character varying (1023),
        description_hash character varying (1023),
        fallback_addr character varying (100),
        cltv_expiry bigint,
        route_hints text,
        payment_addr character (44),
        features text
    )
    """
    cursor.execute(q)


def create_withdraw_txs_table(cursor):
    q = """
    DROP TABLE IF EXISTS withdraw_transactions;

    CREATE TABLE IF NOT EXISTS withdraw_transactions
    (
        userid character varying(100) NOT NULL,
        payment_hash character(64) NOT NULL PRIMARY KEY,
        amount bigint NOT NULL,
        ts_create bigint NOT NULL
    )
    """
    cursor.execute(q)

def create_withdraw_locked_table(cursor):
    q = """
    DROP TABLE IF EXISTS locked_balances;

    CREATE TABLE IF NOT EXISTS locked_balances
    (
        payment_hash character(64) NOT NULL PRIMARY KEY,
        amount bigint NOT NULL
    )
    """
    cursor.execute(q)

def create_users_table(cursor):
    q = """
    DROP TABLE IF EXISTS users;

    CREATE TABLE IF NOT EXISTS users
    (
        userid character varying(100) NOT NULL,
        k1 character(64) NOT NULL PRIMARY KEY,
        lnurlp character varying(300) NOT NULL,
        lnurl character varying(300) NOT NULL
    )
    """
    cursor.execute(q)        

def create_balances_table(cursor):
    q = """
    DROP TABLE IF EXISTS balances;

    CREATE TABLE IF NOT EXISTS balances
    (
        userid character varying (100) NOT NULL,
        k1 character(64) NOT NULL PRIMARY KEY,
        amount bigint DEFAULT 0
    );

    INSERT INTO balances
    VALUES ('user01', 'random_hash_key', 1000000);
    """
    cursor.execute(q)

def create_deposit_transactions_table(cursor):
    q = """
    DROP TABLE IF EXISTS deposit_transactions;

    CREATE TABLE IF NOT EXISTS deposit_transactions
    (
        userid character varying (100) NOT NULL,
        payment_hash character (64) NOT NULL PRIMARY KEY,
        amount bigint NOT NULL,
        ts_create bigint NOT NULL
    )
    """
    cursor.execute(q)
