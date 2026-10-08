# -*- coding: utf-8 -*-
"""临时设备诊断 Spider：只汇报计数和阶段，不记录影片标题、地址或凭据。"""
import copy
import json
import threading
import time
from urllib.parse import urlparse

import requests
from base.spider import Spider as BaseSpider


class Spider(BaseSpider):
    def init(self, extend=''):
        cfg = json.loads(extend) if isinstance(extend, str) and extend else (extend or {})
        base = cfg.get('base_url', 'http://127.0.0.1:8765').rstrip('/')
        parsed = urlparse(base)
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.username or parsed.password:
            raise ValueError('Probe callback must use ADB loopback HTTP')
        self.callback = base + '/test-results'
        self.include_keys = set(cfg.get('include_keys') or [])
        self.max_sources = max(0, int(cfg.get('max_sources', 0)))
        self.runtime_mapping = cfg.get('runtime_mapping') or {}
        self.session = requests.Session()
        self.session.trust_env = False
        self.lock = threading.Lock()
        self.stop_requested = threading.Event()
        self.worker = None
        self.result = {'probe': 'device-list-v1', 'status': 'idle', 'sources': [], 'completed': 0}

    def getName(self):
        return 'Device network probe'

    def homeContent(self, filter):
        return {'class': [{'type_id': 'run', 'type_name': '设备诊断状态'}]}

    def homeVideoContent(self):
        return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        state = self._snapshot()
        status = state['status']
        return {'list': [{'vod_id': 'probe-status', 'vod_name': '诊断状态：' + status,
                          'vod_pic': '', 'vod_remarks': '已检查 %d 个来源' % state['completed']}],
                'page': 1, 'pagecount': 1, 'limit': 1, 'total': 1}

    def detailContent(self, ids):
        return {'list': []}

    def searchContent(self, key, quick, pg='1'):
        return {'list': []}

    def playerContent(self, flag, id, vipFlags):
        return {'parse': 0, 'url': '', 'header': {}}

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def destroy(self):
        if hasattr(self, 'stop_requested'):
            self.stop_requested.set()

    def _snapshot(self):
        with self.lock:
            return copy.deepcopy(self.result)

    def _post(self):
        # 回传失败不影响检测；全部结果仍可经 localProxy action=status 读取。
        try:
            self.session.post(self.callback, json=self._snapshot(), timeout=5)
        except requests.exceptions.RequestException:
            pass

    def _load_runtime(self):
        from java import jclass
        mapping = self.runtime_mapping
        if mapping:
            # 安装 APK 经 R8 混淆时，只使用该 APK 已核对的显式映射。
            holder = jclass(mapping['holder_class'])
            config = getattr(holder, mapping['holder_field'])
            sites = getattr(config, mapping['sites_method'])()
        else:
            sites = jclass('com.fongmi.android.tv.api.config.VodConfig').get().getSites()
        return [sites.get(i) for i in range(sites.size())], jclass('java.util.HashMap')

    @staticmethod
    def _read_json(value):
        if isinstance(value, dict):
            return value
        if value is None or not str(value).strip():
            return {}
        result = json.loads(str(value))
        return result if isinstance(result, dict) else {}

    @staticmethod
    def _skip_reason(key, api, ext):
        lowered = (key + ' ' + api).lower()
        if 'device_probe' in lowered or key == 'device-probe':
            return 'self'
        if any(marker in lowered for marker in ('csp_config', 'csp_push', 'push_agent')):
            return 'configuration_or_push'
        if any(marker in lowered for marker in ('emby', 'pikpakshare', 'p115share', '115share')):
            return 'account_source'
        try:
            values = json.loads(ext) if isinstance(ext, str) and ext.lstrip().startswith('{') else ext
        except (ValueError, TypeError):
            values = None
        if isinstance(values, dict) and any(key in values for key in ('username', 'password', 'pan_115_cookie')):
            return 'account_source'
        return None

    def _stage(self, record, phase, call):
        with self.lock:
            record['stage'] = phase
        self._post()
        try:
            return self._read_json(call())
        except Exception as exc:
            with self.lock:
                record['errors'][phase] = type(exc).__name__
            return {}

    def _run(self):
        try:
            sites, HashMap = self._load_runtime()
            selected = [site for site in sites if not self.include_keys or str(site.getKey()) in self.include_keys]
            if self.max_sources:
                selected = selected[:self.max_sources]
            with self.lock:
                self.result['total'] = len(selected)
            self._post()
            for site in selected:
                if self.stop_requested.is_set():
                    break
                key, api = str(site.getKey()), str(site.getApi())
                record = {'key': key, 'api_format': 'python' if '.py' in api else ('jar' if api.startswith('csp_') else 'other'),
                          'stage': 'starting', 'status': 'running', 'classes': 0,
                          'home_count': 0, 'category_count': 0, 'duration_ms': 0, 'errors': {}}
                with self.lock:
                    self.result['sources'].append(record)
                self._post()
                started = time.monotonic()
                reason = self._skip_reason(key, api, str(site.getExt()))
                if reason:
                    with self.lock:
                        record.update(status='skipped', stage='done', reason=reason)
                else:
                    try:
                        spider = site.spider()
                        home = self._stage(record, 'home', lambda: spider.homeContent(False))
                        classes = home.get('class') or []
                        with self.lock:
                            record['classes'] = len(classes)
                            record['home_count'] = len(home.get('list') or [])
                        videos = self._stage(record, 'home_video', lambda: spider.homeVideoContent())
                        with self.lock:
                            record['home_count'] = max(record['home_count'], len(videos.get('list') or []))
                        if classes and not self.stop_requested.is_set():
                            category_id = str(classes[0].get('type_id', ''))
                            category = self._stage(record, 'category',
                                                   lambda: spider.categoryContent(category_id, '1', False, HashMap()))
                            with self.lock:
                                record['category_count'] = len(category.get('list') or [])
                        with self.lock:
                            record['status'] = ('content' if record['home_count'] or record['category_count']
                                                else ('error' if record['errors'] else 'empty'))
                            record['stage'] = 'done'
                    except Exception as exc:
                        with self.lock:
                            record['status'] = 'error'
                            record['stage'] = 'load'
                            record['errors']['load'] = type(exc).__name__
                with self.lock:
                    record['duration_ms'] = int((time.monotonic() - started) * 1000)
                    self.result['completed'] += 1
                self._post()
            with self.lock:
                self.result['status'] = 'stopped' if self.stop_requested.is_set() else 'done'
        except Exception as exc:
            with self.lock:
                self.result['status'] = 'error'
                self.result['runtime_error'] = type(exc).__name__
                if not self.result['sources']:
                    self.result['runtime_message'] = str(exc)[:240]
        self._post()

    def localProxy(self, params):
        action = params.get('action', 'status')
        if action == 'start':
            with self.lock:
                if self.worker is None or not self.worker.is_alive():
                    self.stop_requested.clear()
                    self.result = {'probe': 'device-list-v1', 'status': 'running', 'sources': [], 'completed': 0}
                    self.worker = threading.Thread(target=self._run, name='tvbox-device-probe', daemon=True)
                    self.worker.start()
        elif action == 'stop':
            self.stop_requested.set()
        return [200, 'application/json', json.dumps(self._snapshot(), ensure_ascii=False)]
