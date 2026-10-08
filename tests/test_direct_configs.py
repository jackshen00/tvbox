"""直连生成器的旧插件接口、路由和资源引用兼容检查（不访问网络）。"""
import importlib.util
import json
from pathlib import Path
import ast
from types import SimpleNamespace
from uuid import uuid4
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('direct_generator', ROOT / 'generate_direct_configs.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class DirectConfigTests(unittest.TestCase):
    def test_legacy_proxy_field_types_and_unrelated_parameters_are_preserved(self):
        ext = {'server': 'https://example.test', 'username': 'test-account',
               'password': 'test-value', 'thread': 3, 'proxy': 'http://127.0.0.1:10172'}
        result = generator.direct_extension(ext)
        self.assertEqual(result['proxy'], '')
        for key in ('server', 'username', 'password', 'thread'):
            self.assertEqual(result[key], ext[key])
        self.assertEqual(result['network_mode'], 'system')
        mapping = generator.direct_extension({'proxy': {'http': 'http://127.0.0.1:10172'}})
        self.assertEqual(mapping['proxy'], {})
        self.assertEqual(ext['proxy'], 'http://127.0.0.1:10172')

    def test_generated_extension_initializes_actual_emby_without_clearing_account(self):
        # 只执行真实 init / _get_proxies 方法，不导入 Android base 或访问账号服务。
        tree = ast.parse((ROOT / 'py/自编/emby.py').read_text(encoding='utf-8'))
        spider = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        methods = [node for node in spider.body if isinstance(node, ast.FunctionDef)
                   and node.name in {'init', '_get_proxies'}]
        namespace = {'json': json, 'uuid4': uuid4}
        exec(compile(ast.Module(body=methods, type_ignores=[]), 'emby-methods', 'exec'), namespace)
        ext = {'server': 'https://example.test/', 'username': 'test-account',
               'password': 'test-value', 'proxy': 'http://127.0.0.1:10172', 'thread': 2}
        instance = SimpleNamespace()
        namespace['init'](instance, json.dumps(generator.direct_extension(ext)))
        self.assertEqual(instance.baseUrl, 'https://example.test')
        self.assertEqual(instance.username, 'test-account')
        self.assertEqual(instance.password, 'test-value')
        self.assertEqual(instance.thread, 2)
        self.assertIsNone(namespace['_get_proxies'](instance))

    def test_json_string_extension_keeps_json_contract(self):
        result = json.loads(generator.direct_extension('{"proxy":"proxy","confirm_115":"0"}'))
        self.assertEqual(result, {'proxy': '', 'confirm_115': '0', 'network_mode': 'system'})

    def test_jar_arguments_keep_positions_without_network_alias(self):
        source = 'null$$$https://example.test$$$proxy2$$$db$$$1'
        result = generator.direct_extension(source).split('$$$')
        self.assertEqual(result, ['null', 'https://example.test', 'noproxy', 'db', '1'])
        self.assertEqual(generator.direct_extension('proxy'), 'noproxy')
        self.assertEqual(generator.direct_extension('https://example.test/proxy'), 'https://example.test/proxy')

    def test_functional_local_processing_and_live_service_are_preserved(self):
        service = 'http://127.0.0.1:10079/image/decrypt/'
        data = {'sites': [{'ext': {'plp': service}}], 'lives': [
            {'url': 'http://127.0.0.1:35456/tv.m3u'},
            {'url': 'http://127.0.0.1:10079/p/0/127.0.0.1:10172/https://example.test/live.m3u'}]}
        result = generator.direct_config(data)
        self.assertEqual(result['sites'][0]['ext']['plp'], service)
        self.assertEqual(result['lives'][0]['url'], data['lives'][0]['url'])
        self.assertEqual(result['lives'][1]['url'], 'https://example.test/live.m3u')

    def test_proxy_rules_are_removed_but_other_rules_remain(self):
        result = generator.direct_config({'proxy': [{'urls': ['http://127.0.0.1:10172']}],
                                          'rules': [{'name': 'proxy'}, {'name': 'media', 'regex': ['abc']}]})
        self.assertEqual(result['proxy'], [])
        self.assertEqual(result['rules'], [{'name': 'media', 'regex': ['abc']}])

    def test_auxiliary_config_disables_proxy_but_retains_other_settings(self):
        data = {'singbox_subscribe_url': 'https://example.test/sub', 'youtube_proxy': 'proxy',
                'pikpak_proxy': 'proxy2', 'tgsearch_api_proxy': 'proxy', 'token': 'test-token',
                'pan115_thread_limit': 3, 'singbox_template_url': './singbox.json'}
        result = generator.direct_helper(data)
        for key in ('singbox_subscribe_url', 'youtube_proxy', 'pikpak_proxy', 'tgsearch_api_proxy'):
            self.assertEqual(result[key], '')
        self.assertEqual(result['token'], '')
        for key in ('pan115_thread_limit', 'singbox_template_url'):
            self.assertEqual(result[key], data[key])

    def test_repo_configs_keep_source_order_and_use_fork_resources(self):
        for name in generator.CONFIGS:
            with self.subTest(name=name):
                source = json.loads((ROOT / name).read_text(encoding='utf-8'))
                result = generator.direct_config(source)
                self.assertEqual([s['key'] for s in result['sites']], [s['key'] for s in source['sites']])
                text = json.dumps(result)
                self.assertNotIn('raw.githubusercontent.com/zw110708/tvbox/main/', text)
                self.assertNotIn('127.0.0.1:10172', text)
                self.assertIn(generator.DEFAULT_BASE_URL + '/' + generator.DIRECT_HELPER, text)
                for site in result['sites']:
                    ext = site.get('ext')
                    if isinstance(ext, dict):
                        self.assertEqual(ext['network_mode'], 'system')

    def test_local_test_base_rewrites_nested_resources_and_helper(self):
        data = {'ext': 'https://raw.githubusercontent.com/zw110708/tvbox/main/lib/zhengjinsong.json$$$https://raw.githubusercontent.com/jackshen00/tvbox/main/lib/douban.json'}
        result = generator.rewrite_urls(data, 'http://127.0.0.1:8765/')
        self.assertEqual(result['ext'], 'http://127.0.0.1:8765/lib/zhengjinsong_direct.json$$$http://127.0.0.1:8765/lib/douban.json')

    def test_direct_configs_select_direct_jar_without_changing_other_jars(self):
        for name in generator.CONFIGS:
            source = json.loads((ROOT / name).read_text(encoding='utf-8'))
            result = generator.direct_config(source)
            self.assertEqual(result['spider'], generator.DEFAULT_BASE_URL + '/jar/pg_direct.jar')
        other = generator.DEFAULT_BASE_URL + '/jar/xpath.jar'
        self.assertEqual(generator.rewrite_urls(other, generator.DEFAULT_BASE_URL), other)
        self.assertEqual(generator.rewrite_urls(generator.DEFAULT_BASE_URL + '/jar/pg.jar',
                                                'http://127.0.0.1:8765'),
                         'http://127.0.0.1:8765/jar/pg_direct.jar')

    def test_published_config_clears_credentials_including_json_string_extensions(self):
        data = {'sites': [{'key': 'account', 'ext': {'server': 'https://example.test',
                         'username': 'test-account', 'password': 'test-value', 'yd_auth': 'test-auth'}},
                         {'key': 'json-account', 'ext': json.dumps({'pan_115_cookie': 'test-cookie'})}]}
        result = generator.direct_config(data)
        self.assertEqual(result['sites'][0]['ext']['username'], '')
        self.assertEqual(result['sites'][0]['ext']['password'], '')
        self.assertEqual(result['sites'][0]['ext']['yd_auth'], '')
        self.assertEqual(result['sites'][0]['ext']['server'], 'https://example.test')
        self.assertEqual(json.loads(result['sites'][1]['ext'])['pan_115_cookie'], '')
        self.assertEqual(data['sites'][0]['ext']['password'], 'test-value')

    def test_public_camel_case_credentials_are_cleared(self):
        result = generator.public_config({'accessToken': 'test-access', 'refreshToken': 'test-refresh',
                                         'privateKey': 'test-private', 'publicLabel': 'keep'})
        self.assertEqual(result, {'accessToken': '', 'refreshToken': '', 'privateKey': '', 'publicLabel': 'keep'})

    def test_public_json_string_arrays_are_sanitized(self):
        original = json.dumps([{'password': 'test-value', 'label': 'keep'}])
        self.assertEqual(json.loads(generator.public_config(original)), [{'password': '', 'label': 'keep'}])

    def test_public_sensitive_scalar_types_are_preserved(self):
        result = generator.public_config({'api_id': 123, 'tokenExpires': 1.5, 'hasToken': True, 'session': None})
        self.assertIs(type(result['api_id']), int)
        self.assertEqual(result['api_id'], 0)
        self.assertIs(type(result['tokenExpires']), float)
        self.assertEqual(result['tokenExpires'], 0.0)
        self.assertIs(result['hasToken'], False)
        self.assertIsNone(result['session'])

    def test_merge_retains_source_order_deduplicates_lives_and_keeps_first_name(self):
        primary = {'spider': 'direct.jar', 'sites': [
            {'key': 'video', 'name': '视频', 'api': 'video.py', 'ext': {'network_mode': 'system'}}],
            'lives': [{'name': '直播', 'url': 'https://example.test/live.m3u'}]}
        secondary = {'spider': 'direct.jar', 'sites': [
            {'key': 'video', 'name': '视频别名', 'api': 'video.py', 'ext': {'network_mode': 'system'}},
            {'key': 'comic', 'name': '漫画', 'api': 'comic.py'}],
            'lives': primary['lives'] + [{'name': '另一直播', 'url': 'https://example.test/other.m3u'}]}
        result = generator.merge_direct_configs([primary, secondary])
        self.assertEqual([s['key'] for s in result['sites']], ['video', 'comic'])
        self.assertEqual(result['sites'][0]['name'], '视频')
        self.assertEqual(len(result['lives']), 2)
        result['sites'][0]['ext']['network_mode'] = 'changed'
        self.assertEqual(primary['sites'][0]['ext']['network_mode'], 'system')
        self.assertEqual(len(primary['sites']), 1)

    def test_merge_rejects_same_key_with_different_parameters(self):
        with self.assertRaisesRegex(ValueError, '重复来源参数冲突'):
            generator.merge_direct_configs([
                {'sites': [{'key': 'same', 'api': 'first.py'}]},
                {'sites': [{'key': 'same', 'api': 'second.py'}]}])

    def test_merge_rejects_no_configs(self):
        with self.assertRaises(ValueError):
            generator.merge_direct_configs([])

    def test_merged_output_contains_all_distinct_sources_and_public_resources(self):
        configs = [generator.direct_config(json.loads((ROOT / name).read_text(encoding='utf-8')))
                   for name in generator.CONFIGS]
        result = generator.merge_direct_configs(configs)
        keys = [s['key'] for s in result['sites']]
        self.assertEqual(len(keys), 81)
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(set(keys), {s['key'] for c in configs for s in c['sites']})
        self.assertEqual(keys[:66], [s['key'] for s in configs[0]['sites']])
        self.assertEqual(len(result['lives']), 4)
        self.assertEqual(result['spider'], generator.DEFAULT_BASE_URL + '/jar/pg_direct.jar')
        self.assertEqual(generator.public_config(result), result)
        self.assertNotIn('raw.githubusercontent.com/zw110708/tvbox/main/', json.dumps(result))
        self.assertEqual(json.loads((ROOT / generator.MERGED_CONFIG).read_text(encoding='utf-8')), result)

    def test_generated_outputs_match_sources(self):
        for name in generator.CONFIGS:
            source = json.loads((ROOT / name).read_text(encoding='utf-8'))
            output = ROOT / f'{Path(name).stem}_direct.json'
            self.assertEqual(json.loads(output.read_text(encoding='utf-8')), generator.direct_config(source))
        helper = json.loads((ROOT / generator.HELPER).read_text(encoding='utf-8'))
        output = json.loads((ROOT / generator.DIRECT_HELPER).read_text(encoding='utf-8'))
        self.assertEqual(output, generator.direct_helper(helper))


if __name__ == '__main__':
    unittest.main()
