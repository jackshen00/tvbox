# TVBox 系统网络配置

这是 `zw110708/tvbox` 的个人 fork，包含播放器配置、Python/JavaScript 来源脚本和 JAR 插件，不是播放器 APK。部分来源包含成人内容。

## 使用

手机先启动 Clash Meta 的 Android VPN/TUN，并确保播放器在代理范围内；电视使用已经具备外网访问能力的系统网络或透明网关。在播放器「设置 → Vod」添加：

```text
https://raw.githubusercontent.com/jackshen00/tvbox/main/tvbox_all_direct.json
```

统一配置 `tvbox_all_direct.json` 合并两份直连配置，按来源 key 去重后包含 81 个来源（含 7 个漫画、3 个小说来源）和 4 个直播入口，资源引用自己的 fork。重复来源保留 `jsm1_direct.json` 的顺序和显示名称；接口或参数冲突会中止生成，避免静默覆盖。原来的 `jsm1_direct.json` / `默影视18_direct.json` 仍保留，兼容已保存的旧链接。洛雪音乐 JS 音源需在音乐客户端单独导入。

Mac 的 `.venv` 不会替代播放器内置的 Android Python 运行环境。

直连版使用系统路由，不依赖 sing-box 的 10172 端口。图片解密、媒体处理和直播服务需要的本地接口仍然保留；网络通畅不能修复失效站点、Cloudflare 验证、账号限制或缺失的本地直播服务。

## 生成与验证

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python build_direct_jar.py
.venv/bin/python generate_direct_configs.py
.venv/bin/python -m unittest discover -s tests -v
```

`build_direct_jar.py` 固定核对原始 `jar/pg.jar` 的 SHA-256，只调整已验证的默认代理和订阅门禁设置，检查 DEX 字符串顺序并刷新校验；输入 JAR 升级时拒绝套用旧补丁。原始配置和 JAR 保留。`requirements.txt` 是依赖范围，`requirements.lock.txt` 是本次验证的实际版本。

## 手机测试工具

`tools/adb_import.py --serial <设备序列号> <URL>` 通过可见播放器界面导入 URL，保留配置历史，不清空应用数据。`tools/device_probe.py` 是临时诊断来源，仅回传计数、阶段和去敏错误，不能证明每条视频都可播放。USB 测试采用 `adb reverse` 的本地 HTTP 服务；断开 USB 后该测试 URL 不能用于重新获取配置，日常使用应换成已发布的仓库 URL。

直连版会清空上游 Cookie、Token 和账号字段，保留接口结构；账号来源须使用自己的账号。原配置保持不变，勿将私人凭据提交到仓库。

当前进度与设备验证结果见 [工作台](docs/01_active_workspace.md)。
