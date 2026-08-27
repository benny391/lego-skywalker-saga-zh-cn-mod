# LEGO Star Wars: The Skywalker Saga 大陆简体中文 Mod 工具链

本仓库从用户自己的 Steam 正版游戏文件生成大陆简体中文 Mod。仓库不包含完整
DAT、官方本地化文本、游戏 EXE、Oodle DLL 或提取后的 FT2。

## 构建模型

字体始终从官方资源重新生成，不再需要 `stableReleaseFont` 或历史
`font-report.json`：

```text
官方 GAME6.DAT
  → 提取官方 font_chinese_nxg.ft2
  → Noto Sans SC Regular 40 px 重绘
  → 两阶段边缘残留清理
  → 53 条 Unicode→glyph 路由修复
  → U+8907 单槽绘制“庞”
  → Release Font
```

已恢复的构建配方会逐字节复现当前游戏内验证版本，关键阶段 SHA-256 为：

```text
官方 FT2       26E625B240BFB0DF8BB2EFF6557F6C87121E0DA069010B85ED97C18BB7495057
初次重绘       E9BDE6B390417FDC0684CFCE1352AC05A33444CD4B27A8F0E4AE9365A8610FB0
边缘清理       511FCD2828C115766F13618ED17C17495C842B09858E74912F197E9B83A7605C
索引修复       76C0177657F873000A8C3D542CC09369F2404C633C45F2404CDA0B4DF9A762D7
最终 Release   CD375749016E18CCB30682320606DDC7BB3F714516F09CF9A194920084C0A93B
```

历史稳定 FT2 可以用于外部回归比较，但不会被构建器读取。

## 两种文本模式

### 1. 导入成熟译文

复制配置并提供本地 `text.csv`：

```powershell
Copy-Item build-config.example.json build-config.json
python build_mod.py --check-only
python build_mod.py
```

`textMode=import` 用于当前经过 LLM、术语统一和人工测试的成熟译文。脚本会把它
与官方 CSV 比较，验证行数、键、非目标语言列、占位符、标签、格式符和控制字符。
导入文件不会提交到公开仓库。

### 2. 从官方繁中重新生成

```powershell
Copy-Item build-config.generate.example.json build-config.json
python build_mod.py
```

`textMode=generate` 使用 OpenCC `tw2sp`、残留 `t2s` 和
[`recipe/mainland_glossary.tsv`](recipe/mainland_glossary.tsv) 离线生成文本。该模式
完全可重复，但没有当前成熟译文的 LLM/人工润色质量。

两种模式最后都会标准化为：`船=726`、运行时 `複=42`。这 42 个 U+8907 只表示
语义字符“庞”；普通“船”使用自己的原生映射。

## 环境和输入

- Windows 10/11
- Python 3.11+
- `python -m pip install -r requirements.txt`
- 当前 Steam 最终版游戏的干净 `GAME.DAT` 和 `GAME6.DAT`
- 游戏自带 `oo2core_8_win64.dll`
- SHA-256 为 `76314658…74A` 的 `NotoSansSC-VF.ttf`

如果实际游戏目录已经安装 Mod，可在私有配置中设置 `officialGameDat` 和
`officialGame6Dat` 指向干净备份。构建器只读取源文件，在独立工作目录中操作。

## 常用命令

```powershell
# 只验证输入
python build_mod.py --check-only

# 只生成并审计 Release Font，不回封 DAT
python build_mod.py --font-only

# 完整生成安装包
python build_mod.py

# 安全清理本工具标记的同一工作目录后重建
python build_mod.py --clean
```

完整构建会提取资源、生成文本、从官方 FT2 构建字体、回封两个 DAT、生成差分
补丁和安装器 ZIP。最终 ZIP 会拒绝包含 `.dat`、`.exe`、`.dll`、`.ft2`、`.csv`
或 `.dds` 完整资源。

## 关键技术事实

- FT2 为 `TNFN` v14；字符记录从偏移 51 开始，步长 28 字节。
- Unicode 表的 `m_charIdx.m_index` 直接索引字符记录。
- Release 图集为 3628×3824 的 BC3/DXT5 DDS，无 mipmap。
- 恢复的历史渲染配方曾使用错位几何解释；这是当前稳定图集的兼容性事实。
- 构建后使用正确 FT2 v14 解析器恢复 53 条路由，只修改 65 个索引字节，DDS 不变。
- “庞”使用 U+8907 / record 2631，像素限制在安全框
  `(200,3030)-(248,3073)`。
- GAME6 回封保留官方 427 个 Oodle 块的数量、大小和边界。

## 安全与许可

- 本项目与 TT Games、Warner Bros. Games、Lucasfilm、Disney 或 LEGO Group 无关联。
- 不要提交或分发完整游戏资源、EXE、Oodle DLL 或官方文本。
- 安装器会先校验官方源哈希，在临时文件上应用补丁，目标哈希正确后才替换资源。
- 字形来自 Noto Sans CJK，遵循 SIL Open Font License 1.1。

