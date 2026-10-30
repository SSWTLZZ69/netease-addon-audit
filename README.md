# NetEase Addon Audit

网易《我的世界》中国版 ModSDK 模组提审前检查工具。目标是在上传前发现可复现的代码与包结构错误，不启动游戏、不上传网易、不修改模组文件。

**这是社区预检，不是网易官方审核器，也不保证审核通过。** 网易的 Pylint/Astroid 版本、完整禁用清单、平台 UUID 登记及内容指纹算法尚未公开确认。

## 检查范围

| 类型 | 检查 |
| --- | --- |
| Python | 语法、静态错误、已知禁用 API、异常重复命名、检查屏蔽指令 |
| 包结构 | 包目录布局、结构文件深度、世界数据混入、文件路径及禁用扩展名 |
| JSON | 编码、语法、数字后缀键范围；内容文件支持 JSONC 注释 |
| manifest | 包身份冲突、版本格式、最低引擎版本、依赖版本、清单一致性 |
| 资源 | 玩家渲染控制器、音频格式与码率、PNG 可读性、位图字体、皮肤透明通道 |
| 发布基线 | 比较历史提交包的身份、内容和版本递增 |
| 权限 | Script API 声明与上传权限配置 |
| ZIP | 完整解压、重复及大小写冲突路径、不安全路径、符号链接、清单外文件 |

默认禁用规则来自实际拒审记录，**不是完整官方禁用列表**。Python 检查固定 Pylint 1.9.5 / Astroid 1.6.6；固定版本用于复现本工具结果，不代表网易使用这些版本。默认禁用 `E1102 (not-callable)`，避免动态回调的可调用性推断误报阻断 CI；真实的不可调用对象调用也不再由此项检查拦截。其余 E/F 诊断保留，部分引擎动态对象可能产生推断误报，需人工判断。

仅忽略引擎提供的 `mod` / `mod.*` 导入解析，未伪造 SDK。因而不验证该命名空间下的 API 是否真实存在。其他前置组件必须在真实提交包内可解析；当前版本没有外部依赖注入接口，平台单独加载的前置组件可能报 E0401，需结合平台依赖配置判断，不能直接当作真实缺失。

## 本地使用

推荐 Docker 隔离已经停止维护的 Python 2.7 环境：

```sh
docker build -t netease-addon-audit /path/to/netease-addon-audit
# 挂载项目为只读，报告目录单独可写；下面示例使用 POSIX shell。
mkdir -p "$PWD/audit-output"
docker run --rm -w /work \
  -v "$PWD:/work:ro" -v "$PWD/audit-output:/output" \
  -e AUDIT_OUTPUT=/output \
  netease-addon-audit --source /work
```

`--source` 必须是 Git 仓库：仅打包所选包目录中的 **Git 跟踪文件的当前工作树内容**；不包括未跟踪文件，也不是 MCSTUDIO 的官方导出。自动发现跟踪的 `manifest.json` / `pack_manifest.json` 所在目录。通用工具不调用项目构建 hook，不合并依赖。

**提交前应优先检查实际准备上传的 ZIP**，避免本工具组包与导出器不同：

```sh
docker run --rm -w /work \
  -v "$PWD:/work:ro" -v "$PWD/audit-output:/output" \
  -e AUDIT_OUTPUT=/output \
  netease-addon-audit --artifact release.zip \
  --baseline accepted.zip --require-baseline
```

ZIP 布局为一个或多个包目录，可有统一外层目录。不支持裸包文件直接位于 ZIP 根目录、嵌套压缩包或世界存档作为提交输入。选定包以外的额外文件会失败；请给出真实 Addon 包或显式配置对应包根。

报告目录必须为新目录（不能已存在 `payload/`），避免上一轮解包内容污染结果。输出：

- `report.json`：结构检查、规则检查、版本比较、内容指纹和告警；**不包含 Pylint 结果**。
- `pylint.txt`：依赖准备和完整 Python 检查日志，保留失败退出码。
- `payload/`：本轮实际检查的解包内容。
- `submission.zip`：仅 `--source` 模式生成，属于候选包；检查失败也可能存在，不能据此认定可发布。

任何结构检查或 Python 检查失败，整体返回非零退出码。没有基线时显式告警；正式提审门禁请用 `--require-baseline`。第一次发布没有旧包时省略该选项，并人工核实 UUID。

已有 Python 2.7 环境可以直接使用（Pylint 应安装在专用虚拟环境）：

```sh
python2 .ci/audit.py --source /path/to/project --output out/check-001
sh .ci/python-audit.sh out/check-001/payload out/check-001
# 或用统一入口，两阶段结果都会影响退出码：
AUDIT_OUTPUT=out/check-002 sh entrypoint.sh --artifact /path/to/release.zip
```

## GitHub Actions 接入

这是 Docker Action，消费者使用 Linux runner。将本仓库推送到你控制的 GitHub 仓库后，替换下面的 `OWNER/netease-addon-audit@COMMIT_SHA` 为实际仓库和固定提交 SHA。

```yaml
name: Submission preflight
on:
  push:
  pull_request:
  workflow_dispatch:
permissions:
  contents: read
jobs:
  audit:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4
      - uses: OWNER/netease-addon-audit@COMMIT_SHA
        with:
          source: .
          # artifact: dist/release.zip  # 先执行项目实际构建，再检查此文件
          # baseline: release-history/accepted.zip
          # require_baseline: 'true'
          # config: addon-audit.json
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: submission-audit
          path: out/audit/
          retention-days: 7
```

本仓库的自身 CI 只检查工具镜像构建、脚本语法及 CLI，不会因为仓库中没有模组包而伪造一个“审核通过”。消费者工作流检查真实模组输入。私有工具仓库跨仓库复用需要在 GitHub Actions 设置里授予访问权限；也可以单独检出工具后 `uses: ./工具目录`。

报告包含源码和候选包，请按项目保密要求设置 artifact 权限及保留期限。不要在来自不可信 PR 的任务里提供网易账号、平台凭据或自托管 runner；本工具不需要这些资源。

## 规则配置

`--config` / Action 的 `config` 接受完整 JSON 配置，例如：

```json
{
  "packs": ["my_behavior_pack", "my_resource_pack"],
  "allow_json_comments": true,
  "allow_sapi": false,
  "require_skin_alpha": true,
  "max_audio_bitrate": 128000,
  "max_texture_pixels": null,
  "max_path_bytes": null,
  "blocked_suffixes": [".mcp", ".pyc", ".pyo"],
  "blocked_python": ["sys", "collections.namedtuple"]
}
```

`packs: []` 自动发现。非空时是相对于源码根 / ZIP 根的精确目录路径，统一使用 `/`。明确配置适合仓库还有示例包、工具模板等不应提交的目录；未选定目录不会由源码模式打包。

禁用 API 扫描基于 AST，收集每个导入及其别名，不执行代码。它不模拟运行时赋值、反射、动态导入或完整词法作用域；不同作用域重用同一别名时可能保守误报。不要利用动态导入绕过真实平台限制。

## 发布基线

基线由调用方按**作品 ID**保存并传入。本工具不会下载任意网络 URL，不自动更新基线，也不把 CI 成功等同于平台接受。

- 同一作品更新：保持 header.uuid，内容变化时 header.version 必须严格递增。
- 版本按整数三元组比较，禁止倒退；未变更内容允许相同版本。
- 指纹按包内相对文件路径和原始文件字节计算，忽略 ZIP 顺序、时间戳、压缩方式以及包外层目录名。
- manifest 的原始字节也计入内容，空白变化同样要求升版；这个本地规则比平台可能更保守。
- 已有包不匹配基线 UUID 时失败，防止通过随机换 UUID 绕过版本检查。独立新作品应使用自己的基线，首次发布需人工核实身份。
- 仅检查输入范围内的 UUID 冲突；无法查询网易全平台或其他未提供作品的 UUID 占用。
- 不支持自动判断平台是否已记录失败提交的版本。维护基线时应结合平台实际状态。

## 官方规则与检查边界

规则依据：[我的世界中国版打包错误信息汇整](https://mc.163.com/m/dev/mcmanual/mc-dev/mcguide/50-常见问题答疑/60-我的世界中国版打包错误信息汇整.html)。本工具仅处理 Addon，不检查地图组件、作品定价、上架接口、平台加密和打包服务内部故障。

- 非 OGG 音频、音频头部码率超过参考值（默认 128000 bps）均为兼容性告警，不会单独导致检查失败；不等同于平台必然拒审。OGG 检查不是全流解码或峰值码率分析，无法确定码率时报告告警，损坏且无法解析的 OGG 文件仍作为错误。
- PNG 检查可读性；位图字体检查 256×256 图集和全零透明像素，不判断字形是否正确。皮肤透明通道规则仅应用于 `skins/` 下的 PNG。
- 最低引擎版本按官方公开要求检查。Script API 默认拒绝；只有确认上传账号已有对应权限后才设置 `allow_sapi=true`，该配置本身不能验证账号权限。
- ZIP 的空目录不参与文件映射，缺少必需目录时给出告警；资源包误放行为实体目录会失败。
- 结构路径按 `structures/` 后超过两个路径分量（包含文件名）提示兼容性告警，不会单独导致检查失败。
- 官方未公布统一纹理像素和路径字节上限，`max_texture_pixels`、`max_path_bytes` 默认不启用；配置后属于调用方的本地预算，不冒充官方阈值。
- UUID 只检查当前输入与显式基线；平台全局占用、官方内容指纹、完整禁用 API、账号权限与运行时表现仍需平台或游戏验证。

Pylint 导入工具模块后才加入提交包路径；静态分析不等于安全沙箱。处理不可信提交应使用隔离容器、只读源码、不提供凭据，并限制运行时间和资源。源文件中的 Pylint 禁用指令会使预检失败，避免诊断被静默屏蔽。

## 当前验证状态

Windows 本机 Python 2.7.18 上已执行真实包扫描与固定版本 Pylint；GitHub Actions 的 Linux runner 已通过 Docker 镜像构建、全部规则模块导入、Python 语法与 CLI 检查。远程 CI 不上传真实模组或模拟网易审核，不代表模组已通过平台机审。工具不会为获得绿灯而改动被检查项目。
