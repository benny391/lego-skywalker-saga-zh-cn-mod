# LEGO Star Wars: The Skywalker Saga 大陆简体中文 Mod 工具链

这是 Steam 版 **LEGO Star Wars: The Skywalker Saga** 大陆简体中文 Mod 的研究记录、转换脚本、字体处理工具、资源回封工具和结构验证器。

仓库只提供工具与技术文档，不包含游戏原始 DAT、官方本地化文本、游戏 EXE、Oodle DLL、解包字体、生成后的完整资源或其他受版权保护的游戏文件。使用者必须自行拥有合法游戏副本。

## 当前稳定且已验证的技术路线

1. 从 `GAME.DAT` 定位并提取 `stuff/text/text.csv`。
2. 将官方繁体中文转换为大陆简体中文，并通过术语表进行语义修订。
3. 保留 ID、占位符、格式说明符、标签、转义序列和控制字符。
4. 使用运行时别名解决官方字体映射中缺少的简体字，并保留已验证稳定的 Release 字体纹理。
5. 使用正确的 FT2 v14 解析器，按 Release 生成时的真实落笔框恢复 `Unicode -> glyph record` 路由。
6. 仅修正 53 个 `m_charIdx.m_index`；DDS/BC3 字体纹理逐字节完全不变。
7. 保持 427 个 Oodle 块的原始数量、大小和边界，只重新压缩包含 Unicode 索引表的两个块。
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

## “飞船→飞葛”定向修复

`build_ship_alias_fix.py` 处理游戏运行时对“船”原生字形槽的异常取字：中文栏中的“船”被编码到一个未使用的内部别名槽，字体中该槽绘制为“船”。该处理保持 UTF-8 字节长度和全部文本结构不变。

## 当前唯一已知字体限制

最终文本需要 2956 个不同汉字，当前稳定方案已以简体字形覆盖 2955 个。唯一保留繁体字形的是 `龐`（42 次）：其中多数属于专名“庞达·巴巴”和“庞沃卡”。Release 字体中不存在可供纯索引复用的“庞”字形，因此默认保留 `龐`，避免为单字重新编码纹理或擅自改写专名。

## 法律与安全说明

- 本项目与 TT Games、Warner Bros. Games、Lucasfilm、Disney 或 LEGO Group 无关联。
- 不要提交或分发完整游戏资源、EXE、Oodle DLL 或官方文本数据。
- 修改前始终保留官方文件备份；Steam 更新或“验证游戏文件完整性”可能恢复官方文件。
- 字体字形来源 Noto Sans CJK，遵循 SIL Open Font License 1.1。

