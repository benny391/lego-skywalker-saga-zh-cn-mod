# LEGO Star Wars: The Skywalker Saga 大陆简体中文 Mod 工具链

这是 Steam 版 **LEGO Star Wars: The Skywalker Saga** 大陆简体中文 Mod 的研究记录、转换脚本、字体处理工具、资源回封工具和结构验证器。

仓库只提供工具与技术文档，不包含游戏原始 DAT、官方本地化文本、游戏 EXE、Oodle DLL、解包字体、生成后的完整资源或其他受版权保护的游戏文件。使用者必须自行拥有合法游戏副本。

## 当前稳定且已验证的技术路线

1. 从 `GAME.DAT` 定位并提取 `stuff/text/text.csv`。
2. 将官方繁体中文转换为大陆简体中文，并通过术语表进行语义修订。
3. 保留 ID、占位符、格式说明符、标签、转义序列和控制字符。
4. 使用运行时别名解决官方字体图集中唯一缺少的简体字，并保留已验证稳定的 Release 字体纹理。
5. 使用正确的 FT2 v14 解析器，按 Release 生成时的真实落笔框恢复 `Unicode -> glyph record` 路由。
6. 修正 53 个 `m_charIdx.m_index`，再将已经过游戏验证的旧“船”别名槽迁移为“庞”。
7. 保持 427 个 Oodle 块的原始数量、大小和边界；单槽迁移只重新压缩对应的四个纹理块。
8. 对生成资源完整解压回读并逐字节验证，然后制作固定哈希差分安装包。

此前使用旧 FT2 解析器进行全图重绘或逐字重绘，会产生错字、截顶、随机黑线，甚至启动失败，已经不再作为发布路线。详细原理、验证门槛和禁止事项见 [`AGENTS.md`](AGENTS.md)。

## 目录

- `tools/`：分析、转换、字体、回封、补丁和 QA 脚本。
- `installer-template/`：带版本哈希检查、备份和卸载功能的 Windows 安装器模板。
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

### “船”别名槽迁移为“庞”

早期版本将 726 个 `船` 编码成未使用的运行时字符 `複`，并把该槽绘制为“船”。正确的 FT2 v14 审计随后已经恢复真实的 `船` 路由（2459→2403），因此这层绕行不再需要。

`build_pang_alias_migration.py` 执行最终迁移：

- 将 726 个运行时 `複` 恢复为真实的 `船`；
- 将 42 个 `龐` 编码为运行时 `複`；
- 只把 U+8907 对应的既有槽 2631 从“船”重绘成“庞”；
- 保持 CSV 字节长度、全部结构、FT2 Unicode 表和字体元数据不变；
- 将像素改动限制在已经验证的安全框 `(200, 3030)-(248, 3073)` 内。

相对纯索引稳定版，迁移只改变 77 个 BC3 块中的 314 个字节。`船` 已完成游戏内确认；“庞”已完成离线字形和资源回封验证。最终文本所需的 2956 个不同汉字现在均有简体显示路径。

## 法律与安全说明

- 本项目与 TT Games、Warner Bros. Games、Lucasfilm、Disney 或 LEGO Group 无关联。
- 不要提交或分发完整游戏资源、EXE、Oodle DLL 或官方文本数据。
- 修改前始终保留官方文件备份；Steam 更新或“验证游戏文件完整性”可能恢复官方文件。
- 字体字形来源 Noto Sans CJK，遵循 SIL Open Font License 1.1。

