#!/usr/bin/python
# -*- coding: utf-8 -*-

import argparse
import getpass
import json
import os
import sys
import uuid
import sys
import platform
import logging
from datetime import datetime, timedelta

from . import config

log = logging.getLogger(__name__)


def parse_unicode(bytestring):
    decoded_string = bytestring.decode(sys.getfilesystemencoding())
    return decoded_string


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-H', '--host', help='Set web server listening host', default='127.0.0.1')
    parser.add_argument('-P', '--port', type=int, help='Set web server listening port', default=5000)
    parser.add_argument('--db', help='Connection String to be used. (default: sqlite)',
                        default='sqlite')
    parser.add_argument('-d', '--debug', type=str.lower, help='Debug Level [info|debug]', default=None)

    return parser.parse_args()


def get_pokemon_name(pokemon_id):
    return get_locale()[str(pokemon_id)]


def get_move_name(move_id):
    return get_locale('moves')[str(move_id)]


def get_locale(property_name='names'):
    '''
    names, moves
    '''
    if (not hasattr(get_locale, 'locale') or config['LOCALE'] != get_locale.locale):
        get_locale.locale = config['LOCALE']
        file_root = os.path.join(config['ROOT_PATH'], config['LOCALES_DIR'])
        if (not hasattr(get_locale, 'names')):
            file_path = os.path.join(file_root, 'pokemon.{}.json'.format(config['LOCALE']))
            with open(file_path, 'r') as f:
                get_locale.names = json.loads(f.read())

        if (not hasattr(get_locale, 'moves')):
            file_path = os.path.join(file_root, 'moves.{}.json'.format(config['LOCALE']))
            if not os.path.isfile(file_path):
                file_path = os.path.join(file_root, 'moves.en.json')
            with open(file_path, 'r') as f:
                get_locale.moves = json.loads(f.read())

    return getattr(get_locale, property_name)


def get_encryption_lib_path():
    # win32 doesn't mean necessarily 32 bits
    if sys.platform == "win32" or sys.platform == "cygwin":
        if platform.architecture()[0] == '64bit':
            lib_name = "encrypt64bit.dll"
        else:
            lib_name = "encrypt32bit.dll"

    elif sys.platform == "darwin":
        lib_name = "libencrypt-osx-64.so"

    elif os.uname()[4].startswith("arm") and platform.architecture()[0] == '32bit':
        lib_name = "libencrypt-linux-arm-32.so"

    elif os.uname()[4].startswith("aarch64") and platform.architecture()[0] == '64bit':
        lib_name = "libencrypt-linux-arm-64.so"

    elif sys.platform.startswith('linux'):
        if "centos" in platform.platform():
            if platform.architecture()[0] == '64bit':
                lib_name = "libencrypt-centos-x86-64.so"
            else:
                lib_name = "libencrypt-linux-x86-32.so"
        else:
            if platform.architecture()[0] == '64bit':
                lib_name = "libencrypt-linux-x86-64.so"
            else:
                lib_name = "libencrypt-linux-x86-32.so"

    elif sys.platform.startswith('freebsd'):
        lib_name = "libencrypt-freebsd-64.so"

    else:
        err = "Unexpected/unsupported platform '{}'".format(sys.platform)
        log.error(err)
        raise Exception(err)

    lib_path = os.path.join(os.path.dirname(__file__), "libencrypt", lib_name)

    if not os.path.isfile(lib_path):
        err = "Could not find {} encryption library {}".format(sys.platform, lib_path)
        log.error(err)
        raise Exception(err)

    return lib_path
