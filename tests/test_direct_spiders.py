"""Isolated networking regressions; never import plugins or contact source sites."""
import ast
import contextlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from urllib.parse import quote, urljoin
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def isolated_class(path, methods, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    source = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    body = [node for node in source.body if isinstance(node, ast.FunctionDef)
            and node.name in methods]
    cls = ast.ClassDef(name='Spider', bases=[], keywords=[], body=body, decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    env = dict(namespace)
    exec(compile(module, str(path), 'exec'), env)
    return env['Spider']


def isolated_functions(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    selected = []
    for name in names:
        selected.append(next(node for node in tree.body
                             if isinstance(node, ast.FunctionDef) and node.name == name))
    module = ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[]))
    env = dict(namespace)
    exec(compile(module, str(path), 'exec'), env)
    return env


class RequestException(Exception):
    def __init__(self, response=None):
        self.response = response


class ProxyError(RequestException):
    pass


class ConnectTimeout(RequestException):
    pass


class HTTPError(RequestException):
    pass


class FakeResponse:
    def __init__(self, status=200, text='content', data=None):
        self.status_code = status
        self.text = text
        self.data = data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise HTTPError(self)

    def json(self):
        return self.data


class FakeSession:
    def __init__(self):
        self.trust_env = True
        self.proxies = {}
        self.headers = {}
        self.calls = []
        self.responses = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        result = self.responses.pop(0) if self.responses else FakeResponse()
        if isinstance(result, Exception):
            raise result
        return result


class FakeRequests(FakeSession):
    exceptions = SimpleNamespace(RequestException=RequestException, ProxyError=ProxyError,
                                 ConnectTimeout=ConnectTimeout)

    def Session(self):
        self.session = FakeSession()
        return self.session


class MemoNetworkingTest(unittest.TestCase):
    def setUp(self):
        self.requests = FakeRequests()
        cls = isolated_class('py/memo.py', {'init', 'fetch'},
                             {'json': json, 'requests': self.requests})
        self.spider = cls()
        self.spider.headers = {'User-Agent': 'test'}

    def test_system_ignores_stale_proxy_and_environment(self):
        self.spider.init(json.dumps({'network_mode': 'system', 'proxy': {'https': 'old'}, 'plp': 'old'}))
        self.assertEqual(self.spider.fetch('https://example.test'), 'content')
        self.assertEqual(self.spider.proxy, {})
        self.assertEqual(self.spider.plp, '')
        self.assertFalse(self.requests.session.trust_env)
        self.assertFalse(self.requests.calls)
        self.assertEqual(self.requests.session.calls[0][1]['proxies'], {})

    def test_proxy_connection_failure_retries_system(self):
        self.spider.init(json.dumps({'proxy': {'https': 'http://127.0.0.1:10172'}}))
        self.requests.responses = [ProxyError(), FakeResponse(text='retried')]
        self.assertEqual(self.spider.fetch('https://example.test'), 'retried')
        self.assertEqual(len(self.requests.calls), 2)
        self.assertNotIn('proxies', self.requests.calls[1][1])

    def test_http_error_is_diagnostic_and_not_retried(self):
        self.spider.init(json.dumps({'proxy': {'https': 'http://127.0.0.1:10172'}}))
        self.requests.responses = [FakeResponse(status=403)]
        with self.assertRaisesRegex(RuntimeError, 'HTTP 403'):
            self.spider.fetch('https://example.test?private=secret')
        self.assertEqual(len(self.requests.calls), 1)

    def test_system_connection_error_does_not_become_empty_list(self):
        self.spider.init(json.dumps({'network_mode': 'system'}))
        self.requests.session.responses = [ProxyError()]
        with self.assertRaisesRegex(RuntimeError, 'ProxyError'):
            self.spider.fetch('https://example.test')
        self.assertEqual(len(self.requests.session.calls), 1)


class EmbyNetworkingTest(unittest.TestCase):
    def setUp(self):
        cls = isolated_class('py/自编/emby.py',
                             {'init', '_get_proxies', '_image_url', 'playerContent'},
                             {'json': json, 'uuid4': uuid4, 'quote': quote})
        self.spider = cls()

    def init(self, mode='system', proxy=False):
        cfg = {'server': 'https://example.test/', 'username': 'test',
               'password': 'test', 'thread': 4, 'network_mode': mode}
        if proxy:
            cfg['proxy'] = 'http://127.0.0.1:10172'
        self.spider.init(json.dumps(cfg))

    def test_missing_proxy_key_keeps_server_settings(self):
        self.init()
        self.assertEqual(self.spider.baseUrl, 'https://example.test')
        self.assertEqual(self.spider.username, 'test')
        self.assertIsNone(self.spider._get_proxies())

    def test_system_image_bypasses_local_port(self):
        self.init(proxy=True)
        self.assertEqual(self.spider._image_url('https://example.test/image'), 'https://example.test/image')
        self.assertIsNone(self.spider._get_proxies())

    def test_legacy_image_and_proxy_unchanged(self):
        self.init(mode='', proxy=True)
        self.assertEqual(self.spider._get_proxies()['https'], 'http://127.0.0.1:10172')
        self.assertIn('127.0.0.1:10172', self.spider._image_url('https://example.test/image'))

    def test_threaded_playback_system_never_initializes_proxy(self):
        self.init(proxy=True)
        self.spider.getAccessToken = lambda: {'User': {'Id': 'test'}}
        self.spider._detect_api_prefix = lambda: ''
        self.spider._request_with_auth_retry = lambda *a, **k: FakeResponse(data={
            'MediaSources': [{'DirectStreamUrl': '/stream'}]})
        self.spider._record_playback_start = lambda *a: 'session'
        self.spider._start_progress_updater = lambda *a: None
        self.spider.fetch = lambda *a, **k: self.fail('system playback must not start local proxy')
        result = self.spider.playerContent('', 'item', [])
        self.assertEqual(result['url'], 'https://example.test/stream')


class GetAVNetworkingTest(unittest.TestCase):
    def setUp(self):
        self.requests = FakeRequests()
        cls = isolated_class('py/自编/GetAV.py',
                             {'init', '_wrap', '_unwrap', '_img', 'isVideoFormat', 'playerContent'},
                             {'json': json, 'requests': self.requests, 'urljoin': urljoin})
        self.spider = cls()

    def test_system_normalizes_images_and_routes_media_directly(self):
        self.spider.init(json.dumps({'network_mode': 'system'}))
        self.assertEqual(self.spider._wrap('https://example.test'), 'https://example.test')
        self.assertEqual(self.spider._unwrap('/test'), 'https://getav.net/test')
        self.assertEqual(self.spider._img('/image.jpg'), 'https://static.worldstatic.com/image.jpg')
        self.assertEqual(self.spider._img('//example.test/image'), 'https://example.test/image')
        self.assertFalse(self.spider.s.trust_env)
        media = self.spider.playerContent('', 'https://example.test/index.txt', [])
        self.assertEqual(media['url'], 'https://example.test/index.txt')
        self.assertEqual(media['parse'], 0)
        self.assertEqual(self.spider.playerContent('', 'https://example.test/page', [])['parse'], 1)

    def test_legacy_bridge_preserved(self):
        self.spider.init('')
        self.assertEqual(self.spider._wrap('https://example.test'),
                         'http://127.0.0.1:10079/p/0/proxy/https://example.test')
        self.assertEqual(self.spider._unwrap(self.spider._wrap('https://example.test')), 'https://example.test')


class B169NetworkingTest(unittest.TestCase):
    def setUp(self):
        cls = isolated_class('py/自编/169新.py', {'init'},
                             {'json': json, 'Session': FakeSession, 'threading': threading})
        cls.default_headers = {}
        cls.host = 'https://example.test'
        cls._check_index_file_age_on_startup = lambda self: None
        self.spider = cls()
        self.helpers = isolated_functions('py/自编/169新.py',
                                         ['_b169_default_proxy', '_b169_get_site_proxy', '_b169_proxies'], {})

    def test_system_base_init_and_shared_proxy_helper(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.spider.init(json.dumps({'network_mode': 'system'}))
        # Cover stale values from earlier init wrappers as well as absent settings.
        self.spider.site_proxy = 'http://127.0.0.1:10172'
        self.assertFalse(self.spider.session.trust_env)
        self.assertEqual(self.helpers['_b169_get_site_proxy'](self.spider), '')
        self.assertIsNone(self.helpers['_b169_proxies'](self.spider))

    def test_legacy_shared_helper_retains_default(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.spider.init('')
        self.assertEqual(self.helpers['_b169_get_site_proxy'](self.spider), 'http://127.0.0.1:10172')


class EmbyProxyNetworkingTest(EmbyNetworkingTest):
    def setUp(self):
        self.requests = FakeRequests()
        self.requests.post = self.requests.get
        cls = isolated_class('py/emby_proxy.py',
                             {'init', '_get_proxies', '_image_url', 'playerContent', 'detailContent'},
                             {'json': json, 'uuid4': uuid4, 'quote': quote, 'requests': self.requests})
        self.spider = cls()

    def test_threaded_playback_system_never_initializes_proxy(self):
        self.init(proxy=True)
        self.spider.getAccessToken = lambda: {'User': {'Id': 'test'}, 'AccessToken': 'test'}
        self.requests.responses = [FakeResponse(data={
            'MediaSources': [{'DirectStreamUrl': '/stream'}]})]
        self.spider._record_playback_start = lambda *a: 'session'
        self.spider._start_progress_updater = lambda *a: None
        self.spider.fetch = lambda *a, **k: self.fail('must not initialize local bridge')
        result = self.spider.playerContent('', 'item', [])
        self.assertEqual(result['url'], 'https://example.test/stream')
        self.assertIsNone(self.requests.calls[0][1]['proxies'])

    def test_detail_request_and_picture_bypass_bridge(self):
        self.init(proxy=True)
        self.spider.getAccessToken = lambda: {'User': {'Id': 'test'}, 'AccessToken': 'test'}
        self.requests.responses = [FakeResponse(data={
            'Name': 'test', 'Id': 'item', 'ImageTags': {'Primary': 'tag'},
            'Genres': [], 'IsFolder': False})]
        result = self.spider.detailContent(['item'])
        self.assertEqual(self.requests.calls[0][0], 'https://example.test/emby/Users/test/Items/item')
        self.assertIsNone(self.requests.calls[0][1]['proxies'])
        self.assertTrue(result['list'][0]['vod_pic'].startswith('https://example.test/'))


class HsexNetworkingTest(unittest.TestCase):
    def setUp(self):
        import urllib.parse
        cls = isolated_class('py/自编/好色TV.py', {'init', 'proxy_url'},
                             {'json': json, 'urllib': __import__('urllib')})
        self.spider = cls()
        self.spider.host = 'https://example.test/'
        self.spider.headers = {}
        self.spider.get_fastest_host = lambda: 'https://example.test/'

    def test_system_relative_and_absolute_urls_preserve_encoding(self):
        self.spider.init(json.dumps({'network_mode': 'system', 'plp': 'old'}))
        self.assertEqual(self.spider.proxy_url('/video.m3u8?token=a%2Fb'),
                         'https://example.test/video.m3u8?token=a%2Fb')
        self.assertEqual(self.spider.proxy_url('//cdn.test/video'), 'https://cdn.test/video')
        self.assertEqual(self.spider.proxy_url('https://cdn.test/video'), 'https://cdn.test/video')

    def test_empty_plp_without_mode_still_normalizes_relative_url(self):
        self.spider.init('')
        self.assertEqual(self.spider.proxy_url('video'), 'https://example.test/video')

    def test_legacy_wrapping_is_idempotent(self):
        self.spider.init(json.dumps({'plp': 'http://127.0.0.1:10079/p/0/proxy/'}))
        expected = 'http://127.0.0.1:10079/p/0/proxy/https%3A//example.test/video'
        self.assertEqual(self.spider.proxy_url('/video'), expected)
        self.assertEqual(self.spider.proxy_url(expected), expected)


if __name__ == '__main__':
    unittest.main()
