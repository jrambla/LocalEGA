# -*- coding: utf-8 -*-

'''
####################################
#
# Database Connection
#
####################################
'''

import logging
from enum import Enum
import aiopg
import psycopg2
import socket

from ..conf import CONF
from .exceptions import FromUser

LOG = logging.getLogger('db')

class Status(Enum):
    Received = 'Received'
    In_Progress = 'In progress'
    Completed = 'Completed'
    Archived = 'Archived'
    Error = 'Error'

def cache_var(v):
    '''Decorator to cache into a global variable'''
    def decorator(func):
        def wrapper(*args, **kwargs):
            g = globals()
            if v not in g:
                g[v] = func(*args, **kwargs)
            return g[v]
        return wrapper
    return decorator

######################################
##           Async code             ##
######################################
async def create_pool(loop, **kwargs):
    return await aiopg.create_pool(**kwargs,loop=loop, echo=True)

async def get_file_info(pool, file_id):
    assert file_id, 'Eh? No file_id?'
    with (await pool.cursor()) as cur:
        query = 'SELECT filename, status, created_at, last_modified, stable_id FROM files WHERE id = %(file_id)s'
        await cur.execute(query, {'file_id': file_id})
        return await cur.fetchone()

async def get_user_info(pool, user_id):
    assert user_id, 'Eh? No user_id?'
    with (await pool.cursor()) as cur:
        query = 'SELECT filename, status, created_at, last_modified, stable_id FROM files WHERE user_id = %(user_id)s'
        await cur.execute(query, {'user_id': user_id})
        return await cur.fetchall()

async def get_internal_user_id(pool, elixir_id):
    assert elixir_id, 'Eh? No elixir_id?'
    with (await pool.cursor()) as cur:
        await cur.execute('SELECT id FROM users WHERE elixir_id = %(elixir_id)s',
                          {'elixir_id': elixir_id})
        return (await cur.fetchone())[0]

######################################
##         "Classic" code           ##
######################################

@cache_var('DB_CONNECTION')
def connect():
    '''Get the database connection (which encapsulates a database session)'''
    user     = CONF.get('db','username')
    password = CONF.get('db','password')
    database = CONF.get('db','dbname')
    host     = CONF.get('db','host')
    port     = CONF.getint('db','port')
    LOG.info(f"Initializing a connection to: {host}:{port}/{database}")
    return psycopg2.connect(user=user, password=password, database=database, host=host, port=port)

def insert_file(filename, enc_checksum, org_checksum, user_id):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT insert_file('
                        '%(filename)s,%(user_id)s,%(enc_checksum)s,%(enc_checksum_algo)s,%(org_checksum)s,%(org_checksum_algo)s,%(status)s'
                        ');',{
                            'filename': filename,
                            'user_id': user_id,
                            'enc_checksum': enc_checksum['hash'],
                            'enc_checksum_algo': enc_checksum['algorithm'],
                            'org_checksum': org_checksum['hash'],
                            'org_checksum_algo': org_checksum['algorithm'],
                            'status' : Status.Received.value })
            return (cur.fetchone())[0]

def set_progress(file_id, staging_name):
    assert file_id, 'Eh? No file_id?'
    assert staging_name, 'Eh? No staging name?'
    LOG.debug(f'Updating status file_id {file_id}')
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE files SET status = %(status)s, staging_name = %(name)s WHERE id = %(file_id)s;',
                        {'status': Status.In_Progress.value, 'file_id': file_id, 'name': staging_name})

def set_error(file_id, error):
    assert file_id, 'Eh? No file_id?'
    assert error, 'Eh? No error?'
    LOG.debug(f'Setting error for {file_id}: {error!s}')
    from_user = isinstance(error,FromUser)
    hostname = socket.gethostname()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT insert_error(%(file_id)s,%(msg)s,%(from_user)s);',
                        {'msg':f"[{hostname}][{error.__class__.__name__}] {error!s}", 'file_id': file_id, 'from_user': from_user})

def get_errors(from_user=False):
    query = 'SELECT * from errors WHERE from_user = true;' if from_user else 'SELECT * from errors;'
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            return cur.fetchall()

def set_encryption(file_id, info, digest):
    assert file_id, 'Eh? No file_id?'
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE files SET reenc_info = %(reenc_info)s, reenc_checksum = %(digest)s, status = %(status)s WHERE id = %(file_id)s;',
                        {'reenc_info': info, 'file_id': file_id, 'digest': digest, 'status': Status.Completed.value})

def finalize_file(file_id, stable_id, filesize):
    assert file_id, 'Eh? No file_id?'
    assert stable_id, 'Eh? No stable_id?'
    LOG.debug(f'Setting final name for file_id {file_id}: {stable_id}')
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE files '
                        'SET status = %(status)s, stable_id = %(stable_id)s, reenc_size = %(filesize)s '
                        'WHERE id = %(file_id)s;',
                        {'stable_id': stable_id, 'file_id': file_id, 'status': Status.Archived.value, 'filesize': filesize})

def get_details(file_id):
    with connect() as conn:
        with conn.cursor() as cur:
            query = 'SELECT filename, org_checksum, org_checksum_algo, stable_id, reenc_checksum from files WHERE id = %(file_id)s;'
            cur.execute(query, { 'file_id': file_id})
            return cur.fetchone()

def insert_user(elixir_id, password_hash, pubkey):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT insert_user(%(eid)s,%(ph)s,%(pk)s);',
                        { 'eid': elixir_id,
                          'ph': password_hash,
                          'pk': pubkey })
            return (cur.fetchone())[0]

def set_user_error(user_id, error):
    assert user_id, 'Eh? No user_id?'
    assert error, 'Eh? No error?'
    LOG.debug(f'User error for {user_id}: {error!s}')
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT insert_user_error(%(user_id)s,%(msg)s);',
                        {'msg':f"{error.__class__.__name__}: {error!s}", 'user_id': user_id})

def get_user(elixir_id):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT id FROM users WHERE elixir_id = (%(elixir_id)s);', { 'elixir_id': elixir_id })
            return (cur.fetchone())[0]
