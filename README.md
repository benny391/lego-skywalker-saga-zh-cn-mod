# LEGO Star Wars: The Skywalker Saga 大陆简体中文 Mod 工具链

这是 Steam 版 **LEGO Star Wars: The Skywalker Saga** 大陆简体中文 Mod 的研究记录、转换脚本、字体处理工具、资源回封工具和结构验证器。

仓库只提供工具与技术文档，不包含游戏原始 DAT、官方本地化文本、游戏 EXE、Oodle DLL、解包字体、生成后的完整资源或其他受版权保护的游戏文件。使用者必须自行拥有合法游戏副本。

## 从零理解当前稳定方案

下面只描述最终方案本身，不按历史试验版本的顺序叙述：

1. 从干净官方 `GAME.DAT` 提取 `stuff/text/text.csv`，将繁体中文转换为自然的大陆简体中文并统一术语。
2. 在整个文本转换过程中，保持 ID、行数、其他语言栏、占位符、格式说明符、标签、转义序列和控制字符不变。
3. 保留稳定 Release 字体图集，使用正确的 FT2 v14 结构恢复 `Unicode -> glyph record` 路由；只修正经过几何证明的 53 个 `m_charIdx.m_index`。
4. 最终所需汉字中只有 `庞` 没有可直接使用的 FT2 Unicode 映射，因此在运行时把语义字符 `庞` 编码为未被正文使用的 U+8907 `複`，并只将其既有 glyph record 2631 绘制成“庞”。
5. `GAME.DAT` 中的文本使用 ZIPX 回封，`GAME6.DAT` 中的字体使用原 427 个 Oodle 块、原大小和原边界回封。
6. 对两个资源进行完整解压回读和逐字节比较，再校验最终 DAT 固定哈希。
7. 只分发由干净官方 DAT 到 Mod DAT 的差分补丁、安装器和校验信息。

此前使用旧 FT2 解析器进行全图重绘或逐字重绘，会产生错字、截顶、随机黑线，甚至启动失败，已经不再作为发布路线。详细原理、验证门槛和禁止事项见 [`AGENTS.md`](AGENTS.md)。

## 目录

- `build_mod.py`：唯一的一键构建入口，自动执行审计、字体修复、回封、回读验证、差分补丁及安装包制作。
- `build-config.example.json`：一键构建的路径配置示例。
- `tools/`：分析、转换、字体、回封、补丁和 QA 脚本。
- `installer-template/`：带版本哈希检查、备份和卸载功能的 Windows 安装器模板。
- `licenses/`：构建产物需要附带的开源字体许可证。
- 本地调查报告包含安装细节与版本哈希，因此不放入公开仓库。

## 环境

- Windows 10/11
- Python 3.11+
- Pillow
- OpenCC 1.1.9
- 合法游戏安装目录中的 `oo2core_8_win64.dll`
- Noto Sans SC Variable Font（构建机路径通常为 `C:\Windows\Fonts\NotoSansSC-VF.ttf`）

```powershell
python -m pip install -r requirements.txt
```

## 一键制作当前 Mod

仓库的统一入口是 `build_mod.py`。它不会修改游戏安装目录，而是在独立工作目录复制官方 DAT 后完成以下阶段：

1. 校验官方 `GAME.DAT`、`GAME6.DAT` 和三个稳定构建输入的大小及 SHA-256；
2. 调用几何审计工具并强制检查 `3076/3073/3/0` 不变量；
3. 调用纯索引修复工具并强制检查 53 条路由、65 个变化字节和 DDS 不变；
4. 生成最终运行时文本和字体；只有 `庞` 使用 U+8907 别名槽；
5. 在官方 DAT 的副本中回封文本与字体，并将资源完整解压回读、逐字节比较；
6. 校验生成 DAT 是否等于已验证的当前 Mod 哈希；
7. 生成 `.gpatch` 差分补丁、安装器 manifest、校验和及最终 ZIP；
8. 检查 ZIP 中不存在完整 DAT、EXE、DLL、FT2、CSV 或 DDS。

首次使用：

```powershell
Copy-Item build-config.example.json build-config.json
# 编辑 build-config.json 中的本机路径
python build_mod.py --check-only
python build_mod.py
```

重复构建同一工作目录和版本时，显式使用：

```powershell
python build_mod.py --clean
```

`--clean` 只会删除带有本工具专用标记的构建目录，并替换同版本的 ZIP/构建报告；不会删除或覆盖游戏目录中的文件。最终安装包输出到配置的 `outputDirectory`。

### 必须自行提供的三个构建检查点

出于版权原因，这三个缓存检查点不会提交到 GitHub，但当前可重复构建需要它们：

- `stableRuntimeText`：经过翻译、术语统一和结构 QA 的运行时 `text.csv` 检查点；
- `stableReleaseFont`：经过游戏验证、尚未进行 53 路由修复的字体检查点；
- `releaseFontBuildReport`：生成该 Release 字体时的 `font-report.json`。

它们是为了避免公开仓库分发官方文本和解包字体而采用的私有缓存，并不改变上面的从零原理。示例配置把它们放在被 `.gitignore` 排除的 `inputs/` 下。脚本内置当前稳定版本的精确 SHA-256；输入不是已验证版本时会立即停止，不会尝试“差不多能用”的构建。官方 DAT 和 Oodle DLL 同样必须来自使用者自己的合法游戏副本。

如果游戏目录当前已经安装了 Mod，可在私有的 `build-config.json` 中增加
`officialGameDat` 和 `officialGame6Dat`，指向你保留的干净官方备份；构建脚本仍不会改动这些源文件。

## 数据目录约定

工具最初按下面的工作目录布局编写。输入资源需要由使用者自行从游戏副本提取：

```text
tools/
  extracted/
    stuff/text/text.csv
    ui/font/localisation/font_chinese_nxg.ft2
  phase3/
  runtime_phase3/
  all_han_inplace/
  surgical_dotfix/
  surgical_dotfix_all/
```

脚本包含严格的源文件 SHA-256 和固定大小检查。游戏更新后，应先重新调查资源结构并更新已验证哈希，不要绕过检查直接覆盖。

边缘残留修复脚本不会在公开源码中硬编码官方资源指纹。运行前分别设置
`TSS_EDGE_FIX_SOURCE_SHA256` 和 `TSS_ORPHAN_FIX_SOURCE_SHA256` 为你从合法游戏副本生成并验证的输入文件哈希。

## 关键验证

`localization_qa.py` 比较转换前后资源并检查：

- 行数和复合键一致；
- 非目标语言列完全一致；
- 占位符、printf 格式、标签、资源引用、转义序列和控制字符一致；
- 不产生意外空字符串；
- CSV 可按 UTF-8 严格重新解析。

字体脚本会检查 Unicode 映射和 FT2 元数据不变、修改范围没有逃出目标安全框、重新解码后的像素变化符合预期。

### 纯索引字体修复

- `ft2_v14.py`：经过实测验证的 FT2 v14 记录及 Unicode 映射解析器。
- `audit_release_geometry_routes.py`：根据 Release 构建报告中的真实落笔框恢复物理 glyph record。
- `build_release_geometry_index_fix.py`：只修改唯一且无冲突的 53 个索引字段，并验证 DDS 完全不变。

几何审计覆盖 3076 个重绘汉字，其中 3073 个拥有唯一完整包含的物理槽，目标槽冲突为 0。3020 个索引原本正确，53 个需要移动；`一、二、日` 三个特殊记录保持 Release 原样。

### 唯一特殊别名：庞

最终资源的规则是：

- 除 `庞` 外，所需汉字均使用常规 Unicode 映射；
- 42 个语义上的 `庞` 以运行时 U+8907 `複` 存储，由 record 2631 显示为“庞”；
- 只重绘 U+8907 对应的既有槽 2631；
- 保持 CSV 字节长度、全部结构、FT2 Unicode 表和字体元数据不变；
- 将像素改动限制在已经验证的安全框 `(200, 3030)-(248, 3073)` 内。

相对纯索引字体，最终单槽绘制只改变 77 个 BC3 块中的 314 个字节。常规字符路径已完成游戏内确认；“庞”已完成离线字形和资源回封验证。最终文本所需的 2956 个不同汉字均有简体显示路径。

## 法律与安全说明

- 本项目与 TT Games、Warner Bros. Games、Lucasfilm、Disney 或 LEGO Group 无关联。
- 不要提交或分发完整游戏资源、EXE、Oodle DLL 或官方文本数据。
- 修改前始终保留官方文件备份；Steam 更新或“验证游戏文件完整性”可能恢复官方文件。
- 字体字形来源 Noto Sans CJK，遵循 SIL Open Font License 1.1。

