#!/usr/bin/env python
u"""
scp_pgc_dem_strips.py
Written by Tyler Sutterley (06/2022)
Copies PGC REMA DEM and ArcticDEM strip data between a
    local host and a remote host

PUSH to remote: s.put(local_file, remote_file)

CALLING SEQUENCE:
    python scp_pgc_dem_strips.py --host <host> --user <username> \
        --remote <path_to_remote> --verbose --mode 0o775

COMMAND LINE OPTIONS:
    -h, --help: list the command line options
    --host X: Remote server host
    --user X: Remote server username
    -D X, --directory X: Local working directory
    -d X, --remote X: Remote working directory
    -Y X, --year X: Year to sync
    -C, --clobber: overwrite existing data in transfer
    -V, --verbose: output information about each synced file
    -L, --list: only list files to be transferred
    -T X, --timeout X: Timeout in seconds for blocking operations
    -R X, --retry X: Connection retry attempts
    -M X, --mode X: permission mode of directories and files copied

PYTHON DEPENDENCIES:
    paramiko: Native Python SSHv2 protocol library
        http://www.paramiko.org/
        https://github.com/paramiko/paramiko
    scp: scp module for paramiko
        https://github.com/jbardin/scp.py

UPDATE HISTORY:
    Written 06/2022
"""
from __future__ import print_function, division

import sys
import os
import re
import scp
import getpass
import logging
import argparse
import builtins
import paramiko
import posixpath

#-- PURPOSE: create argument parser
def arguments():
    parser = argparse.ArgumentParser(
        description="""Copies PGC strip data between a
            local host and remote host
            """
    )
    #-- command line parameters
    #-- remote server credentials
    parser.add_argument('--host','-H',
        type=str, default='',
        help='Hostname of the remote server')
    parser.add_argument('--user','-U',
        type=str, default='',
        help='Remote server username')
    #-- working data directories
    parser.add_argument('--directory','-D',
        type=lambda p: os.path.abspath(os.path.expanduser(p)),
        default=os.getcwd(),
        help='Local working directory')
    parser.add_argument('--remote','-d',
        type=str, default='',
        help='Remote working directory')
    #-- years to sync
    years = list(range(2007,2018))
    parser.add_argument('--year','-Y', metavar='YEAR',
        type=int, choices=years, default=years, nargs='+',
        help='Years to sync')
    #-- instrument to sync
    choices = ('GE01','W1W1','W1W2','W1W3','W2W2','W2W3','W3W3',
        'WV01','WV02','WV03','WV04')
    parser.add_argument('--instrument','-I', metavar='INSTRUMENT',
        type=str, choices=choices, default=choices, nargs='+',
        help='Instrument to sync')
    #-- sync options
    parser.add_argument('--list','-L',
        default=False, action='store_true',
        help='Only print files that could be transferred')
    #-- connection timeout and number of retry attempts
    parser.add_argument('--timeout','-T',
        type=int, default=120,
        help='Timeout in seconds for blocking operations')
    parser.add_argument('--retry','-R',
        type=int, default=5,
        help='Connection retry attempts')
    #-- verbose will output information about each copied file
    parser.add_argument('--verbose','-V',
        default=False, action='store_true',
        help='Verbose output of run')
    #-- clobber will overwrite the existing data
    parser.add_argument('--clobber','-C',
        default=False, action='store_true',
        help='Overwrite existing data')
    #-- permissions mode of the local directories and files (number in octal)
    parser.add_argument('--mode','-M',
        type=lambda x: int(x,base=8), default=0o775,
        help='Permissions mode of output directories and files')
    # return the parser
    return parser

# This is the main part of the program that calls the individual functions
def main():
    #-- Read the system arguments listed after the program
    parser = arguments()
    args,_ = parser.parse_known_args()

    #-- use entered host and username
    client_kwds = {}
    client_kwds.setdefault('hostname',args.host)
    client_kwds.setdefault('username',args.user)
    #-- use ssh configuration file to extract hostname, user and identityfile
    user_config_file = os.path.join(os.environ['HOME'],".ssh","config")
    if os.path.exists(user_config_file):
        #-- read ssh configuration file and parse with paramiko
        ssh_config = paramiko.SSHConfig()
        with open(user_config_file) as f:
            ssh_config.parse(f)
        #-- lookup hostname from list of hosts
        user_config = ssh_config.lookup(args.host)
        client_kwds['hostname'] = user_config['hostname']
        #-- get username if not entered from command-line
        if args.user is None and 'username' in user_config.keys():
            client_kwds['username'] = user_config['user']
        #-- use identityfile if in ssh configuration file
        if 'identityfile' in user_config.keys():
            client_kwds['key_filename'] = user_config['identityfile']

    #-- open HOST ssh client for USER (and use password if no IDENTITYFILE)
    client = attempt_login(**client_kwds)
    #-- open secure FTP client
    client_ftp = client.open_sftp()
    #-- verbosity settings
    if args.verbose or args.list:
        logging.getLogger("paramiko").setLevel(logging.INFO)
        logging.basicConfig(level=logging.INFO)
    else:
        logging.basicConfig(level=logging.CRITICAL)
    #-- print username for remote client
    logging.info('{0}@{1}:\n'.format(client_kwds['username'],
        client_kwds['hostname']))

    #-- run copy program
    scp_pgc_dem_strips(client, client_ftp, args.directory, args.remote,
        YEARS=args.year, INSTRUMENT=args.instrument, LIST=args.list,
        TIMEOUT=args.timeout, RETRY=args.retry, CLOBBER=args.clobber,
        MODE=args.mode)

    #-- close the secure FTP server
    client_ftp.close()
    #-- close the ssh client
    client = None

#-- PURPOSE: try logging onto the server and catch authentication errors
def attempt_login(**client_kwds):
    #-- open HOST ssh client
    kwds = client_kwds.copy()
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    tryagain = True
    #-- add initial attempt
    attempts = 1
    #-- use identification file
    try:
        client.connect(**kwds)
    except paramiko.ssh_exception.AuthenticationException:
        pass
    else:
        return client
    #-- add attempt
    attempts += 1
    #-- phrase for entering password
    phrase = 'Password for {0}@{1}: '.format(kwds['username'],kwds['hostname'])
    #-- remove key_filename from keywords
    kwds.pop('key_filename') if 'key_filename' in kwds.keys() else None
    #-- enter password securely from command-line
    while tryagain:
        kwds['password'] = getpass.getpass(phrase)
        try:
            client.connect(*kwds)
        except paramiko.ssh_exception.AuthenticationException:
            pass
        else:
            kwds.pop('password')
            return client
        #-- retry with new password
        logging.critical('Authentication Failed (Attempt {0:d})'.format(attempts))
        tryagain = builtins.input('Try Different Password? (Y/N): ') in ('Y','y')
        #-- add attempt
        attempts += 1
    #-- exit program if not trying again
    sys.exit()

#-- PURPOSE: copies PGC strip files between a remote host and a local host
def scp_pgc_dem_strips(client, client_ftp, DIRECTORY, REMOTE,
    YEARS=None, INSTRUMENT=None, TIMEOUT=None, RETRY=None,
    CLOBBER=False, LIST=False, MODE=0o775):
    #-- find PGC strip files for given years
    RXI = r'|'.join([I for I in INSTRUMENT]) if INSTRUMENT else r'\w{4}'
    RXY = r'|'.join([str(Y) for Y in YEARS]) if YEARS else r'\d+'
    regex_pattern = (r'SETSM_({0})_({1})(\d{{2}})(\d{{2}})_(\w+)_(\w+)_'
        r'(seg\d+)_(\d+m)_(v\d+\.\d+)_(\w+).tif$')
    rx = re.compile(regex_pattern.format(RXI,RXY), re.VERBOSE)
    file_list = [fi for fi in os.listdir(DIRECTORY) if rx.match(fi)]
    #-- for each file to run
    for fi in sorted(file_list):
        #-- extract parameters from file
        INST,YY,MM,DD,S1,S2,SEG,RES,VERS,TYPE = rx.findall(fi).pop()
        # SUBDIRECTORY = '{0}.{1}.{2}'.format(YY,MM,DD)
        SUBDIRECTORY = '{0}'.format(YY)
        remote_path = os.path.join(REMOTE,SUBDIRECTORY)
        #-- check if data directory exists and recursively create if not
        remote_makedirs(client_ftp, remote_path, LIST=LIST, MODE=MODE)
        #-- push file from local to remote
        scp_push_file(client, client_ftp, fi, DIRECTORY, remote_path,
            CLOBBER=CLOBBER, LIST=LIST, TIMEOUT=TIMEOUT, RETRY=RETRY,
            MODE=MODE)

#-- PURPOSE: recursively create directories on remote server
def remote_makedirs(client_ftp, remote_dir, LIST=False, MODE=0o775):
    dirs = remote_dir.split(posixpath.sep)
    remote_path = dirs[0] if dirs[0] else posixpath.sep
    # for each part of the directory
    for s in dirs:
        # skip invalid directories
        if (s == posixpath.sep) or not s:
            continue
        # create directory if non-existent
        if (s not in client_ftp.listdir(remote_path)) and not LIST:
            client_ftp.mkdir(posixpath.join(remote_path,s), MODE)
        # add to remote path
        remote_path = posixpath.join(remote_path,s)

#-- PURPOSE: push a local file to a remote host checking if file exists
#-- and if the local file is newer than the remote file (reprocessed)
#-- set the permissions mode of the remote transferred file to MODE
def scp_push_file(client, client_ftp, transfer_file, local_dir, remote_dir,
    CLOBBER=False, LIST=False, TIMEOUT=None, RETRY=None, MODE=0o775):
    #-- local and remote versions of file
    local_file = os.path.join(local_dir,transfer_file)
    remote_file = posixpath.join(remote_dir,transfer_file)
    #-- check if local file is newer than the remote file
    TEST = False
    OVERWRITE = 'clobber'
    if (transfer_file in client_ftp.listdir(remote_dir)):
        local_mtime = os.stat(local_file).st_mtime
        remote_mtime = client_ftp.stat(remote_file).st_mtime
        #-- if local file is newer: overwrite the remote file
        if (even(local_mtime) > even(remote_mtime)):
            TEST = True
            OVERWRITE = 'overwrite'
    else:
        TEST = True
        OVERWRITE = 'new'
    #-- if file does not exist remotely, is to be overwritten, or CLOBBER is set
    if TEST or CLOBBER:
        logging.info('{0} --> '.format(local_file))
        logging.info('\t{0} ({1})\n'.format(remote_file,OVERWRITE))
        #-- if not only listing files
        if not LIST:
            retry_scp_push(client, client_ftp, local_file, remote_file,
                TIMEOUT=TIMEOUT, RETRY=RETRY)
            #-- change the permissions level of the transported file to MODE
            client_ftp.chmod(remote_file, MODE)

#-- PURPOSE: Try pushing a file up to a set number of times
def retry_scp_push(client, client_ftp, local_file, remote_file,
    TIMEOUT=None, RETRY=1):
    #-- attempt to download up to the number of retries
    retry_counter = 0
    while (retry_counter < RETRY):
        #-- attempt to retrieve file from https server
        try:
            #-- copy local files to remote server
            with scp.SCPClient(client.get_transport(), socket_timeout=TIMEOUT) as s:
                s.put(local_file, remote_file, preserve_times=True)
            local_length = os.path.getsize(local_file)
        except Exception as e:
            pass
        else:
            #-- check that synced file matches original length
            remote_length = client_ftp.stat(remote_file).st_size
            if (local_length == remote_length):
                break
        #-- add to retry counter
        retry_counter += 1
    #-- check if maximum number of retries were reached
    if (retry_counter == RETRY):
        raise TimeoutError('Maximum number of retries reached')

#-- PURPOSE: rounds a number to an even number less than or equal to original
def even(i):
    return 2*int(i//2)

#-- run main program
if __name__ == '__main__':
    main()
