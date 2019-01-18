import copy
import json
import logging
import os
import six
from subprocess import check_output
import yaml

from uaclient import util

LOG = logging.getLogger(__name__)

__VERSION__ = '18.1'
PACKAGED_VERSION = '@@PACKAGED_VERSION@@'

DEFAULT_CONFIG_FILE = '/etc/ubuntu-advantage/uaclient.conf'
BASE_AUTH_URL = 'https://login.ubuntu.com'
BASE_SERVICE_URL = 'https://uaservice.canonical.com'

CACHE_DIR = '/var/cache/ubuntu-advantage-tools/'
MOTD_CACHE_FILE = CACHE_DIR + 'motd-ubuntu-advantage-status.cache'
MOTD_ESM_CACHE_FILE = CACHE_DIR + 'motd-esm-status.cache'

CONFIG_DEFAULTS = {
    'sso_auth_url': BASE_AUTH_URL,
    'service_url': BASE_SERVICE_URL,
    'data_dir': '/var/lib/ubuntu-advantage',
    'log_level': logging.INFO
}


class ConfigAbsentError(RuntimeError):
    """Raised when no valid config is discovered."""
    pass


class UAConfig(object):

    data_paths = {'accounts': 'accounts.json',
                  'account-contracts': 'account-contracts.json',
                  'account-users': 'account-users.json',
                  'machine-contracts': 'machine-contracts.json',
                  'machine-access-esm': 'machine-access-esm.json',
                  'machine-access-fips': 'machine-access-fips.json',
                  'machine-access-fips-updates':
                      'machine-access-fips-updates.json',
                  'machine-access-livepatch': 'machine-access-livepatch.json',
                  'machine-detach': 'machine-detach.json',
                  'machine-token': 'machine-token.json',
                  'macaroon': 'sso-macaroon.json',
                  'oauth': 'sso-oauth.json'}

    _contracts = None  # caching to avoid repetitive file reads
    _entitlements = None  # caching to avoid repetitive file reads
    _machine_token = None  # caching to avoid repetitive file reading

    def __init__(self, cfg=None):
        """"""
        if cfg:
            self.cfg = cfg
        else:
            self.cfg = parse_config()

    @property
    def accounts(self):
        """Return the list of accounts that apply to this authorized user."""
        return self.read_cache('accounts')

    @property
    def contract_url(self):
        return self.cfg['contract_url']

    @property
    def data_dir(self):
        return self.cfg['data_dir']

    @property
    def log_level(self):
        return self.cfg.get('log_level', CONFIG_DEFAULTS['log_level'])

    @property
    def sso_auth_url(self):
        return self.cfg['sso_auth_url']

    @property
    def contracts(self):
        """Return the list of contracts that apply to this account."""
        if not self._contracts:
            self._contracts = self.read_cache('account-contracts')
        return self._contracts or []

    @property
    def entitlements(self):
        """Return the machine-token if cached in the machine token response."""
        if self._entitlements:
            return self._entitlements
        self._entitlements = {}
        for contract in self.contracts:
            ent_names = contract['contractInfo']['resourceEntitlements'].keys()
            for entitlement_name in ent_names:
                self._entitlements[entitlement_name] = self.read_cache(
                    'machine-access-%s' % entitlement_name)
        return self._entitlements

    @property
    def is_attached(self):
        """Report whether this machine configuration is attached to UA."""
        return bool(self.machine_token)   # machine_token is removed on detach

    @property
    def machine_token(self):
        """Return the machine-token if cached in the machine token response."""
        if not self._machine_token:
            self._machine_token = self.read_cache('machine-token')
        return self._machine_token

    def data_path(self, key):
        """Return the file path in the data directory represented by the key"""
        if not key:
            return self.cfg['data_dir']
        if key in self.data_paths:
            return os.path.join(self.cfg['data_dir'], self.data_paths[key])
        return os.path.join(self.cfg['data_dir'], key)

    def read_cache(self, key):
        cache_path = self.data_path(key)
        if not os.path.exists(cache_path):
            logging.debug('File does not exist: %s', cache_path)
            return None
        content = util.load_file(cache_path)
        json_content = util.maybe_parse_json(content)
        return json_content if json_content else content

    def write_cache(self, key, content):
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
        filepath = self.data_path(key)
        if not isinstance(content, six.string_types):
            content = json.dumps(content)
        util.write_file(filepath, content)


def parse_config(config_path=None):
    """Parse known UA config file

    Attempt to find configuration in cwd and fallback to DEFAULT_CONFIG_FILE.
    Any missing configuration keys will be set to CONFIG_DEFAULTS.

    Values are overridden by any environment variable with prefix 'UA_'.

    @param config_path: Fullpath to ua configfile. If unspecified, use
        DEFAULT_CONFIG_FILE.

    @raises: ConfigAbsentError when no config file is discovered.
    @return: Dict of configuration values.
    """
    if not config_path:
        config_path = DEFAULT_CONFIG_FILE
    cfg = copy.copy(CONFIG_DEFAULTS)
    local_cfg = os.path.join(os.getcwd(), os.path.basename(config_path))
    if os.path.exists(local_cfg):
        config_path = local_cfg
    if os.environ.get('UA_CONFIG_FILE'):
        config_path = os.environ.get('UA_CONFIG_FILE')
    LOG.debug('Using UA client configuration file at %s', config_path)
    if os.path.exists(config_path):
        cfg.update(yaml.load(util.load_file(config_path)))
    env_keys = {}
    for key, value in os.environ.items():
        if key.startswith('UA_'):
            env_keys[key.lower()[3:]] = value   # Strip leading UA_
    cfg.update(env_keys)
    cfg['log_level'] = cfg['log_level'].upper()
    cfg['data_dir'] = os.path.expanduser(cfg['data_dir'])
    return cfg


def get_version(_args=None):
    """Return the package version if set, otherwise return git describe."""
    if not PACKAGED_VERSION.startswith('@@PACKAGED_VERSION'):
        return PACKAGED_VERSION
    topdir = os.path.dirname(os.path.dirname(__file__))
    if os.path.exists(os.path.join(topdir, '.git')):
        return util.decode_binary(check_output([
            'git', 'describe', '--abbrev=8', '--match=[0-9]*',
            '--long']).strip())
    return __VERSION__
