#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import configparser

from docopt import docopt

__doc__ = f'''

Utility to help bootstrap a LocalEGA instance.

Usage:
   {sys.argv[0]} [options] <conf>

Options:
   -h, --help               Prints this help and exit
   -v, --version            Prints the version and exits
   -V, --verbose            Prints more output
   --secrets <prefix>       Use this prefix for the docker secrets
   --queue <q>              Queue to listen to
   --destination <section>  "to" storage prefix
   --routing_key <q>        Routing key when done
 
'''

def main(conf, args):
    """Create ingest.ini"""

    with_docker_secrets = args['--secrets']

    config = configparser.RawConfigParser()
    config['DEFAULT'] = {
        'queue': args['--queue'],
        'exchange': 'lega',
        'routing_key': args['--routing_key'],
    }

    config['destination'] = {
        'location': args['--destination'],
    }

    mq_connection = ('secret:///run/secrets/mq.connection'
                     if with_docker_secrets else
                     conf.get('mq', 'connection') + '?' + conf.get('mq', 'connection_params'))

    config['broker'] = {
        'connection': mq_connection,
        'enable_ssl': 'yes',
        'verify_peer': 'yes',
        'verify_hostname': 'no',
        'cacertfile': '/etc/ega/CA.cert',
        'certfile': '/etc/ega/ssl.cert',
        'keyfile': '/etc/ega/ssl.key',
    }

    db_connection = ('secret:///run/secrets/db.connection'
                     if with_docker_secrets else
                     conf.get('db', 'connection') + '?' + conf.get('db', 'connection_params'))

    config['db'] = {
        'connection': db_connection,
        'try': 30,
        'try_interval': 1,
    }

    # output
    config.write(sys.stdout)


if __name__ == '__main__':
    args = docopt(__doc__,
                  sys.argv[1:],
                  help=True,
                  version='LocalEGA ingestion service boostrap (version 0.2)')
    conf = configparser.RawConfigParser()
    conf.read(args['<conf>'])
    main(conf, args)
