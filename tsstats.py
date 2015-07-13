import re
import glob
import json
import logging
import datetime
from os import sep
import configparser
from sys import argv
from time import mktime
from os.path import exists
from jinja2 import Environment, FileSystemLoader


class Clients:

    def __init__(self):
        self.clients_by_id = {}
        self.clients_by_uid = {}

    def is_id(self, id_or_uid):
        try:
            int(id_or_uid)
            return True
        except ValueError:
            return False

    def __add__(self, id_or_uid):
        if self.is_id(id_or_uid):
            if id_or_uid not in self.clients_by_id:
                self.clients_by_id[id_or_uid] = Client(id_or_uid)
        else:
            if id_or_uid not in self.clients_by_uid:
                self.clients_by_uid[id_or_uid] = Client(id_or_uid)
        return self

    def __getitem__(self, id_or_uid):
        if self.is_id(id_or_uid):
            if id_or_uid not in self.clients_by_id:
                self += id_or_uid
            return self.clients_by_id[id_or_uid]
        else:
            if id_or_uid not in self.clients_by_uid:
                self += id_or_uid
            return self.clients_by_uid[id_or_uid]

clients = Clients()


class Client:

    def __init__(self, identifier):
        # public
        self.identifier = identifier
        self.nick = None
        self.connected = 0
        self.onlinetime = 0
        self.kicks = 0
        self.pkicks = 0
        self.bans = 0
        self.pbans = 0
        # private
        self._last_connect = 0

    def connect(self, timestamp):
        '''
        client connects at "timestamp"
        '''
        logging.debug('CONNECT {}'.format(str(self)))
        self.connected += 1
        self._last_connect = timestamp

    def disconnect(self, timestamp):
        '''
        client disconnects at "timestamp"
        '''
        logging.debug('DISCONNECT {}'.format(str(self)))
        if not self.connected:
            logging.debug('^ disconnect before connect')
            raise Exception('disconnect before connect!')
        self.connected -= 1
        session_time = timestamp - self._last_connect
        self.onlinetime += session_time

    def kick(self, target):
        '''
        client kicks "target" (Client-obj)
        '''
        logging.debug('KICK {} -> {}'.format(str(self), str(target)))
        target.pkicks += 1
        self.kicks += 1

    def ban(self, target):
        '''
        client bans "target" (Client-obj)
        '''
        logging.debug('BAN {} -> {}'.format(str(self), str(target)))
        target.pbans += 1
        self.bans += 1

    def __str__(self):
        return '<{},{}>'.format(self.identifier, self.nick)

    def __format__(self):
        return self.__str__()

    def __getitem__(self, item):
        return {
            'identifier': self.identifier,
            'nick': self.nick,
            'connected': self.connected,
            'onlinetime': self.onlinetime,
            'kicks': self.kicks,
            'pkicks': self.pkicks,
            'bans': self.bans,
            'pbans': self.pbans,
        }[item]

# check cmdline-args
abspath = sep.join(__file__.split(sep)[:-1]) + sep
config_path = argv[1] if len(argv) >= 2 else 'config.ini'
config_path = abspath + config_path
id_map_path = argv[2] if len(argv) >= 3 else 'id_map.json'
id_map_path = abspath + id_map_path

if not exists(config_path):
    raise Exception('Couldn\'t find config-file at {}'.format(config_path))

if exists(id_map_path):
    # read id_map
    id_map = json.load(open(id_map_path))
else:
    id_map = {}

# parse config
config = configparser.ConfigParser()
config.read(config_path)
# check keys
if 'General' not in config:
    raise Exception('Invalid config! Section "General" missing!')
general = config['General']
html = config['HTML'] if 'HTML' in config.sections() else {}
if not ('logfile' in general or 'outputfile' in general):
    raise Exception('Invalid config! "logfile" and/or "outputfile" missing!')
log_path = general['logfile']
output_path = general['outputfile']
debug = general.get('debug', 'false') in ['true', 'True']
debug_file = general.get('debugfile', str(debug)) in ['true', 'True']
title = html.get('title', 'TeamspeakStats')

# setup logging
log = logging.getLogger()
log.setLevel(logging.DEBUG)
# create handler
if debug and debug_file:
    file_handler = logging.FileHandler('debug.txt', 'w', 'UTF-8')
    file_handler.setFormatter(logging.Formatter('%(message)s'))
    file_handler.setLevel(logging.DEBUG)
    log.addHandler(file_handler)

# stream handler
stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO)
log.addHandler(stream_handler)

re_dis_connect = re.compile(r"'(.*)'\(id:(\d*)\)")
re_disconnect_invoker = re.compile(r"invokername=(.*)\ invokeruid=(.*)\ reasonmsg")

# find all log-files and collect lines
log_files = [file_name for file_name in glob.glob(log_path) if exists(file_name)]
log_lines = []
for log_file in log_files:
    for line in open(log_file, 'r'):
        log_lines.append(line)


def get_client(clid):
    if clid in id_map:
        clid = id_map[clid]
    client = clients[clid]
    client.nick = nick
    return client

# process lines
for line in log_lines:
    parts = line.split('|')
    logdatetime = int(datetime.datetime.strptime(parts[0], '%Y-%m-%d %H:%M:%S.%f').timestamp())
    data = '|'.join(parts[4:]).strip()
    if data.startswith('client'):
        nick, clid = re_dis_connect.findall(data)[0]
        if data.startswith('client connected'):
            client = get_client(clid)
            client.connect(logdatetime)
        elif data.startswith('client disconnected'):
            client = get_client(clid)
            client.disconnect(logdatetime)
            if 'invokeruid' in data:
                re_disconnect_data = re_disconnect_invoker.findall(data)
                invokernick, invokeruid = re_disconnect_data[0]
                invoker = clients[invokeruid]
                invoker.nick = invokernick
                if 'bantime' in data:
                    invoker.ban(client)
                else:
                    invoker.kick(client)

# render template
template = Environment(loader=FileSystemLoader(abspath)).get_template('template.html')

# sort all values desc
cl_by_id = clients.clients_by_id
cl_by_uid = clients.clients_by_uid


def get_sorted(key, uid):
    clients = cl_by_uid.values() if uid else cl_by_id.values()
    return sorted([(client, client[key]) for client in clients if client[key] > 0], key=lambda data: data[1], reverse=True)

clients_onlinetime_ = get_sorted('onlinetime', False)
clients_onlinetime = []
for client, onlinetime in clients_onlinetime_:
    minutes, seconds = divmod(client.onlinetime, 60)
    hours, minutes = divmod(minutes, 60)
    hours = str(hours) + 'h ' if hours > 0 else ''
    minutes = str(minutes) + 'm ' if minutes > 0 else ''
    seconds = str(seconds) + 's' if seconds > 0 else ''
    clients_onlinetime.append((client, hours + minutes + seconds))


clients_kicks = get_sorted('kicks', True)
clients_pkicks = get_sorted('pkicks', False)
clients_bans = get_sorted('bans', True)
clients_pbans = get_sorted('pbans', False)
objs = [('Onlinetime', clients_onlinetime), ('Kicks', clients_kicks),
        ('passive Kicks', clients_pkicks),
        ('Bans', clients_bans), ('passive Bans', clients_pbans)]  # (headline, list)

with open(output_path, 'w') as f:
    f.write(template.render(title=title, objs=objs, debug=debug))
