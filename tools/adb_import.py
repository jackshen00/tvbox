#!/usr/bin/env python3
"""通过已授权 ADB 手机界面导入配置；保留播放器历史，不清空应用数据。"""
import argparse
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

PACKAGE = 'com.fongmi.android.tv'
class Device:
    def __init__(self, serial, adb='adb'):
        self.serial, self.adb = serial, adb
    def call(self, *args):
        result = subprocess.run([self.adb, '-s', self.serial, *args], check=True,
                                text=True, capture_output=True, timeout=25)
        return result.stdout
    def snapshot(self):
        self.call('shell', 'uiautomator', 'dump', '/sdcard/tvbox-test-ui.xml')
        return ET.fromstring(self.call('shell', 'cat', '/sdcard/tvbox-test-ui.xml'))
    def tap(self, node):
        left, top, right, bottom = map(int, re.findall(r'\d+', node.get('bounds', '')))
        self.call('shell', 'input', 'tap', str((left+right)//2), str((top+bottom)//2))
    def find(self, root, resource):
        return next((n for n in root.iter('node') if n.get('resource-id') == resource), None)
    def import_config(self, url):
        if not re.fullmatch(r'[A-Za-z0-9:/._%-]+', url):
            raise ValueError('使用编码后的 URL，不接受 shell/input 特殊字符')
        root = self.snapshot()
        for _ in range(4):
            setting = self.find(root, PACKAGE+':id/setting')
            if setting is not None: break
            self.call('shell', 'input', 'keyevent', '4'); root=self.snapshot()
        if setting is None: raise RuntimeError('请将播放器置于可见状态')
        self.tap(setting); root=self.snapshot()
        row = self.find(root, PACKAGE+':id/vodUrl')
        if row is None: raise RuntimeError('找不到 Vod 订阅设置')
        self.tap(row); root=self.snapshot()
        field=self.find(root, PACKAGE+':id/url')
        if field is None: raise RuntimeError('找不到订阅输入框')
        self.tap(field)
        self.call('shell','input','keycombination','113','29')
        self.call('shell','input','keyevent','67')
        prefix, tail = url.split('://', 1)
        # 避开输入首字母 h/f 时播放器自动追加协议的行为。
        self.call('shell','input','text',tail)
        self.call('shell','input','keyevent','122')
        self.call('shell','input','text',prefix+'://')
        self.call('shell','input','keyevent','4')
        root=self.snapshot(); field=self.find(root,PACKAGE+':id/url')
        if field is None or field.get('text')!=url: raise RuntimeError('订阅输入校验失败')
        button=self.find(root,'android:id/button1')
        if button is None: raise RuntimeError('找不到确认按钮')
        self.tap(button)
        for _ in range(10):
            root=self.snapshot();row=self.find(root,PACKAGE+':id/vodUrl')
            if row is not None and row.get('text')==url:
                print('订阅已保存:',url);return
            time.sleep(1)
        raise RuntimeError('订阅未保存，请检查播放器错误和配置服务')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial',required=True);parser.add_argument('--adb',default='adb')
    parser.add_argument('url');args=parser.parse_args()
    Device(args.serial,args.adb).import_config(args.url)
