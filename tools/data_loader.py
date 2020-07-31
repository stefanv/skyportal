#!/usr/bin/env python

import os
import sys
import base64
from pathlib import Path
import textwrap
from contextlib import contextmanager
import time

import requests
import pandas as pd
import yaml
from yaml import Loader
import tdtax

from baselayer.app.env import load_env, parser
from baselayer.app.model_util import status
from skyportal.tests import api


@contextmanager
def status(message):
    print(f'[·] {message}', end='')
    try:
        yield
    except Exception as e:
        print(f'\r[✗] {message}: {repr(e)}')
    else:
        print(f'\r[✓] {message}')


if __name__ == "__main__":
    parser.description = 'Load data into SkyPortal'
    parser.add_argument('data_files', type=str, nargs='+',
                        help='YAML files with data to load')
    parser.add_argument('--host',
                        help=textwrap.dedent('''Fully specified URI of the running SkyPortal instance.
                             E.g., https://myserver.com:9000.

                             Defaults to http://localhost on the port specified
                             in the SkyPortal configuration file.'''))
    parser.add_argument('--token',
                        help=textwrap.dedent('''Token required for accessing the SkyPortal API.

                             By default, SkyPortal produces a token that is
                             written to .tokens.yaml.  If no token is specified
                             here, that token will be used.'''))

    env, cfg = load_env()

    ## TODO: load multiple files
    if len(env.data_files) > 1:
        raise NotImplementedError("Cannot yet handle multiple data files")

    fname = env.data_files[0]
    src = yaml.load(open(fname, "r"), Loader=Loader)

    def get_token():
        if env.token:
            return env.token

        try:
            token = yaml.load(open('.tokens.yaml'), Loader=yaml.Loader)['INITIAL_ADMIN']
            print('Token loaded from `.tokens.yaml`')
            return token
        except:
            print('Error: no token specified, and no suitable token found in .tokens.yaml')
            sys.exit(-1)

    print('Testing connection...', end='')

    RETRIES = 5
    for i in range(RETRIES):
        try:
            admin_token = get_token()

            def get(endpoint, token=admin_token):
                response_status, data = api("GET", endpoint,
                                            token=token,
                                            host=env.host)
                return response_status, data

            def post(endpoint, data, token=admin_token):
                response_status, data = api("POST", endpoint,
                                            data=data,
                                            token=token,
                                            host=env.host)
                return response_status, data

            def assert_post(endpoint, data, token=admin_token):
                response_status, data = post(endpoint, data, token)
                if not response_status == 200 and data["status"] == "success":
                    raise RuntimeError(
                        f'API call to {endpoint} failed with status {status}: {data["message"]}'
                    )
                return data

            code, data = get('sysinfo')

            if code == 200:
                break
            else:
                if i == RETRIES - 1:
                    print('FAIL')
                else:
                    time.sleep(2)
                    print('Reloading auth tokens and trying again...', end='')
                continue
        except requests.exceptions.ConnectionError:
            if i == RETRIES - 1:
                print('FAIL')
                print()
                print('Error: Could not connect to SkyPortal instance; please ensure ')
                print('       it is running at the given host/port')
                sys.exit(-1)
            else:
                time.sleep(2)
                print('Retrying connection...')

    if code not in (200, 400):
        print(f'Error: could not connect to server (HTTP status {code})')
        sys.exit(-1)

    if data['status'] != 'success':
        print('Error: Could not authenticate against SkyPortal; please specify a valid token.')
        sys.exit(-1)

    code, response = get('groups/public')
    if code != 200:
        print('Error: no public group found; aborting')
        sys.exit(-1)
    public_group_id = response['data']['id']

    error_log = []

    references = {
        'public_group_id': public_group_id
    }

    def inject_references(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                obj[k] = inject_references(v)
            return obj
        elif isinstance(obj, str) and obj.startswith('='):
            try:
                return references[obj[1:]]
            except KeyError:
                print(f'\nReference {obj[1:]} not found while posting to {endpoint}; skipping')
                raise
        elif isinstance(obj, list):
            return [inject_references(item) for item in obj]
        else:
            return obj

    for endpoint, to_post in src.items():
        # Substitute references in path
        endpoint_parts = endpoint.split('/')
        try:
            for i, part in enumerate(endpoint_parts):
                if part.startswith('='):
                    endpoint_parts[i] = str(references[part[1:]])
        except KeyError:
            print(f'\nReference {part[1:]} not found while interpolating endpoint {endpoint}; skipping')
            continue

        endpoint = '/'.join(endpoint_parts)

        print(f'Posting to {endpoint}: ', end='')
        if 'file' in to_post:
            filename = to_post['file']
            post_objs = yaml.load(open(to_post['file'], 'r'), Loader=yaml.Loader)
        else:
            post_objs = to_post

        for obj in post_objs:
            if 'file' in obj:
                filename = obj['file']
                if filename.endswith('csv'):
                    df = pd.read_csv(filename)
                    obj.pop('file')
                    obj.update(df.to_dict(orient='list').keys())
                else:
                    raise NotImplementedError('Only CSV files currently supported for extending individual objects')

            # Fields that start with =, such as =id, get saved for using as
            # references later on
            saved_fields = {v: k[1:] for k, v in obj.items() if k.startswith('=')}

            # Remove all such fields from the object to be posted
            obj = {k: v for k, v in obj.items() if not k.startswith('=')}

            # Replace all references of the format field: =key or [=key, ..]
            # with the appropriate reference value
            try:
                inject_references(obj)
            except KeyError:
                continue

            status, response = post(endpoint, data=obj)

            print('.' if status == 200 else 'X', end='')
            if status != 200:
                error_log.append(f"/{endpoint}: {response['message']}")
                continue

            # Save all references from the response
            for target, field in saved_fields.items():
                references[target] = response['data'][field]

        print()

    if error_log:
        print("\nError log:")
        print("----------")
        print("\n".join(error_log))

        sys.exit(-1)
