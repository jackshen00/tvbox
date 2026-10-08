# 当前工作台

## 目标

Android 手机通过 Clash Meta 系统 VPN 使用项目配置，电视通过已有系统网络使用；移除对 10172 的依赖，保留来源与必要的本地处理。

## Last position

2026-10-08：`generate_direct_configs.py` 生成两份直连配置及辅助配置；`build_direct_jar.py` 生成独立 `pg_direct.jar`；6 个 Python 来源修复系统网络兼容。手机已通过 USB 临时配置验证 Memo 列表（10 条）和样本播放（时间从约 8 秒推进到 45 秒）。原始配置仍保留在播放器历史。

## 已验证事实

- 仓库 main，origin 指向 jackshen00/tvbox；保留 Gemini 的初始修改与用户 `.idea/`。
- 直连配置保留 66 / 77 来源及原顺序；内部项目资源指向个人 fork。
- 39 项回归检查通过；新 JAR 的 Android dexdump 和 ZIP 完整性通过。
- `.venv` 使用本机 Python 3.13 / OpenSSL，依赖已安装；pip check 通过。
- 手机播放器版本 5.6.9，Clash Meta 已运行；USB 本地测试配置导入成功。

## 手机来源验证

两份配置共有 81 个不同点播来源（重合来源 API/ext 一致）：63 个返回列表、10 个空结果、1 个报错；5 个账号来源及 2 个配置/推送项跳过。仅检测首页、推荐及首分类，不代表全视频播放通过。详见 [手机验证报告](reports/001_device_validation.html)。

4 个直播入口：本地合并入口 HTTP 400，远端资源入口 HTTP 404，PHP 入口 HTTP 200 / 22 条 M3U；内嵌接口返回 200 但未识别到 M3U/TXT，未验证播放。

## 进行中

- 用户已明确授权 commit / push；准备发布本次修改并把手机切换到正式仓库链接。
- 发布后复测手机 Raw 订阅与 Memo；恢复原自动旋转设置（原值 accelerometer_rotation=1，user_rotation=0）。

## 未解决限制

- 系统网络模式无法保证失效源、Cloudflare 验证、账号源或本地 allinone 服务可用。
- 169 来源已有 `_jbf_*` 未定义符号，可能影响匹配/解析；不是本次修改引入。
- 原配置仍继承上游公开凭据；直连输出已清空 Cookie、Token、账号字段，不复制发布。账号来源需用户提供自己的账号。
- USB localhost 配置不是日常订阅地址；本地改动尚未提交、推送或发布。

## 用户已批准行动

本地代码修复、创建 `.venv` 与安装依赖、通过已连接 ADB 手机导入与测试。已明确授权 commit / push 与手机使用正式链接。
