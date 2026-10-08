#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成使用系统网络的配置；手机 Clash VPN/TUN 和电视透明网关可共用。

保留原配置、来源顺序和必要的本地处理服务。公开直连输出清空账号凭据；原始配置保持不变。
默认引用自己的 fork；--base-url 可用于 ADB 本地 HTTP 对照测试。
"""
import argparse
import copy
import json
import re
from pathlib import Path

DEFAULT_BASE_URL = 'https://raw.githubusercontent.com/jackshen00/tvbox/main'
REPO_URL = re.compile(r'https://raw\.githubusercontent\.com/(?:zw110708|jackshen00)/tvbox/main/')
PROXY_ALIAS = re.compile(r'^proxy\d*$')
# 仅取消经 sing-box 的网络转发，不取消解密、直播等本地服务。
NETWORK_PREFIX = re.compile(r'^http://127\.0\.0\.1:10079/p/0/(?:127\.0\.0\.1:1017[2-7]|proxy\d*)/')
CONFIGS = ('jsm1.json', '默影视18.json')
HELPER = 'lib/zhengjinsong.json'
DIRECT_HELPER = 'lib/zhengjinsong_direct.json'


def rewrite_urls(value, base_url):
    if isinstance(value, str):
        value = REPO_URL.sub(base_url.rstrip('/') + '/', value)
        value = value.replace('/' + HELPER, '/' + DIRECT_HELPER)
        return re.sub(r'/jar/pg\.jar(?=$|[;?#$])', '/jar/pg_direct.jar', value)
    if isinstance(value, list):
        return [rewrite_urls(item, base_url) for item in value]
    if isinstance(value, dict):
        return {key: rewrite_urls(item, base_url) for key, item in value.items()}
    return value


def direct_extension(ext):
    """字段存在性及类型是部分旧脚本接口的一部分。"""
    if isinstance(ext, dict):
        result = copy.deepcopy(ext)
        if 'proxy' in result:
            result['proxy'] = {} if isinstance(result['proxy'], dict) else ''
        if isinstance(result.get('plp'), str) and NETWORK_PREFIX.match(result['plp']):
            result['plp'] = ''
        result['network_mode'] = 'system'
        return result
    if isinstance(ext, str):
        # 部分 Python 插件接收 JSON 字符串，而 JAR 使用 $$$ 位置参数。
        try:
            decoded = json.loads(ext)
        except (json.JSONDecodeError, ValueError):
            decoded = None
        if isinstance(decoded, dict):
            return json.dumps(direct_extension(decoded), ensure_ascii=False, separators=(',', ':'))
        # Java split 会丢弃末尾空槽；未知短标签 noproxy 经 pg.jar 解析为空代理。
        return '$$$'.join('noproxy' if PROXY_ALIAS.fullmatch(part.strip()) else part
                          for part in ext.split('$$$'))
    return ext


SENSITIVE_KEY = re.compile(r'cookie|password|user.?name|token|secret|session|private.?key|api.?hash|api.?id|(?:^|[_-])auth$|authorization|api.?key|credential', re.I)


def public_config(value):
    """发布配置保留字段结构，但不复制源作者的账号数据。"""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if SENSITIVE_KEY.search(key):
                if isinstance(item, dict):
                    item = {}
                elif isinstance(item, list):
                    item = []
                elif isinstance(item, bool):
                    item = False
                elif isinstance(item, (int, float)):
                    item = type(item)(0)
                elif item is not None:
                    item = ''
            result[key] = public_config(item)
        return result
    if isinstance(value, list):
        return [public_config(item) for item in value]
    if isinstance(value, str) and value.lstrip().startswith(('{', '[')):
        try:
            decoded = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return value
        if isinstance(decoded, (dict, list)):
            return json.dumps(public_config(decoded), ensure_ascii=False, separators=(',', ':'))
    return value


def direct_config(data, base_url=DEFAULT_BASE_URL):
    result = copy.deepcopy(data)
    for site in result.get('sites', []):
        if 'ext' in site:
            site['ext'] = direct_extension(site['ext'])
        if str(site.get('api', '')).endswith('/GetAV.py') and not isinstance(site.get('ext'), dict):
            site['ext'] = {'proxy': '', 'network_mode': 'system'}
    for live in result.get('lives', []):
        if isinstance(live.get('url'), str):
            live['url'] = NETWORK_PREFIX.sub('', live['url'])
    # 顶层代理映射全部由设备 VPN / 系统路由取代，避免空 urls 触发播放器默认值。
    result['proxy'] = []
    result['rules'] = [rule for rule in result.get('rules', []) if rule.get('name') != 'proxy']
    return public_config(rewrite_urls(result, base_url))


def direct_helper(data, base_url=DEFAULT_BASE_URL):
    result = copy.deepcopy(data)
    for key in result:
        if key in {'singbox_subscribe_url', 'youtube_proxy', 'pikpak_proxy', 'tgsearch_api_proxy', 'proxy'}:
            result[key] = ''
    return public_config(rewrite_urls(result, base_url))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def make_direct_config(source_path, target_path, base_url=DEFAULT_BASE_URL):
    source_path, target_path = Path(source_path), Path(target_path)
    data = json.loads(source_path.read_text(encoding='utf-8'))
    write_json(target_path, direct_config(data, base_url))
    print(f'生成 {target_path.name}: 保留 {len(data.get("sites", []))} 个来源')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default=DEFAULT_BASE_URL, help='仓库根目录 HTTP 地址')
    parser.add_argument('--output-dir', type=Path, help='输出根目录（默认项目根目录）')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    output = args.output_dir or root
    for name in CONFIGS:
        make_direct_config(root / name, output / f'{Path(name).stem}_direct.json', args.base_url)
    write_json(output / DIRECT_HELPER, direct_helper(json.loads((root / HELPER).read_text(encoding='utf-8')), args.base_url))
    print(f'生成 {DIRECT_HELPER}: 已清空内置代理订阅与显式代理设置')


if __name__ == '__main__':
    main()
