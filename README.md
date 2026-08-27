# LEGO Star Wars: The Skywalker Saga 大陆简体中文 Mod

本项目为 Steam 版 **LEGO Star Wars: The Skywalker Saga** 制作大陆简体中文资源，
包括本地化文本、简体中文字形、自动校验工具和差分补丁安装器。

仓库只提供构建工具和公开配方，不包含完整游戏 DAT、游戏 EXE、Oodle DLL、官方
本地化文本或提取后的字体资源。构建时必须使用用户自己的正版游戏文件。

## 安装已经发布的 Mod

1. 从 GitHub Releases 下载最新安装包并完整解压。
2. 确认游戏已经关闭。
3. 运行 `Install.cmd`，按提示选择 Steam 游戏目录。
4. 在游戏中选择繁体中文；该语言槽会加载 Mod 的大陆简体中文资源。

安装器只接受受支持的官方游戏文件。它会先验证源文件和补丁的 SHA-256，在临时
文件上应用补丁，并在目标哈希正确后替换资源。原文件保存在游戏目录下的
`_SimplifiedChineseMod_Backup`。需要卸载时运行 `Uninstall.cmd`。

## 从源码构建

### 环境

- Windows 10/11
- Python 3.11+
- Steam 正版游戏目录
- 游戏自带的 `oo2core_8_win64.dll`
- `NotoSansSC-VF.ttf`，SHA-256：
  `763146584CF0710223441356B4395E279021B0806C196614377A7A0174AE074A`

安装 Python 依赖：

```powershell
python -m pip install -r requirements.txt
```

构建器支持以下官方资源：

| 文件 | 大小 | SHA-256 |
| --- | ---: | --- |
| `GAME.DAT` | 4,064,897,269 | `F959070D32437B4DE81B3ABA62D2AF42274CE7687242753591DEC569999AF55D` |
| `GAME6.DAT` | 1,643,610,491 | `1DF529C6532324545581CE6144321991FEEDF046BD9F06F024239518015650CF` |

如果游戏目录已经安装 Mod，请在本地 `build-config.json` 中用 `officialGameDat` 和
`officialGame6Dat` 指向干净备份。构建器只读取这些源文件，所有修改都发生在独立
工作目录中。

### 选择文本模式

项目提供两种互相独立的文本来源：

| 模式 | 文本来源 | 特点 |
| --- | --- | --- |
| `import` | 外部提供的完整简体中文 `text.csv` | 可使用经过人工校对和语义润色的译文 |
| `generate` | 官方繁中 + OpenCC + 项目术语表 | 完全离线、可重复生成，但语言质量偏机械 |

无论使用哪种模式，脚本都会验证字符串数量、ID、非中文列、占位符、格式符、标签、
控制字符、空字符串、编码和最终文件长度。

#### 导入译文

```powershell
Copy-Item build-config.example.json build-config.json
```

把译文放到配置中的 `translatedText` 路径，并按实际文件填写
`translatedTextSha256`。项目使用的成熟译文不随源码仓库分发。

#### 从官方繁中生成

```powershell
Copy-Item build-config.generate.example.json build-config.json
```

该模式从官方 `GAME.DAT` 提取繁体中文，依次使用 OpenCC `tw2sp`、残留 `t2s` 和
[`recipe/mainland_glossary.tsv`](recipe/mainland_glossary.tsv) 生成简体中文。

### 执行构建

```powershell
# 只检查配置和输入文件
python build_mod.py --check-only

# 只生成并审计游戏字体，不回封 DAT
python build_mod.py --font-only

# 完整构建差分补丁和安装器 ZIP
python build_mod.py

# 清理本工具标记的工作目录后重新构建
python build_mod.py --clean
```

完整构建会：

1. 从官方 DAT 提取繁体中文文本和中文 FT2 字体。
2. 按所选文本模式生成或导入简体中文。
3. 使用 Noto Sans SC 构建游戏中文字体并修复字符索引。
4. 对修改后的文本和字体执行结构及哈希校验。
5. 在工作目录内回封两个 DAT，并验证资源可以再次提取。
6. 生成 `.gpatch` 差分补丁、安装脚本、清单、校验文件和最终 ZIP。

最终 ZIP 不允许包含完整 `.dat`、`.exe`、`.dll`、`.ft2`、`.csv` 或 `.dds` 文件。

## 字体构建

字体从官方 `font_chinese_nxg.ft2` 和指定版本的 Noto Sans SC 生成：

```text
官方 GAME6.DAT
  → 提取中文 FT2
  → Noto Sans SC Regular 40 px 绘制字形
  → 清理图集边缘残留
  → 修复 53 条 Unicode→glyph 索引
  → 写入“庞”的兼容字形
  → 最终游戏字体
```

各阶段使用固定哈希验证构建结果：

| 阶段 | SHA-256 |
| --- | --- |
| 官方 FT2 | `26E625B240BFB0DF8BB2EFF6557F6C87121E0DA069010B85ED97C18BB7495057` |
| 字形绘制 | `E9BDE6B390417FDC0684CFCE1352AC05A33444CD4B27A8F0E4AE9365A8610FB0` |
| 边缘清理 | `511FCD2828C115766F13618ED17C17495C842B09858E74912F197E9B83A7605C` |
| 索引修复 | `76C0177657F873000A8C3D542CC09369F2404C633C45F2404CDA0B4DF9A762D7` |
| 最终字体 | `CD375749016E18CCB30682320606DDC7BB3F714516F09CF9A194920084C0A93B` |

游戏字体没有可供简体“庞”直接使用的字符槽。构建器借用繁体“複”的 U+8907
槽位绘制“庞”，同时把文本中的“庞”编码为 U+8907。该编码只用于游戏运行时的
字体兼容，画面中显示的仍然是“庞”。

## 技术说明

- FT2 文件头为 `TNFN`，版本 14。
- 字符记录从偏移 51 开始，每条 28 字节。
- Unicode 表中的 `m_charIdx.m_index` 直接索引字符记录。
- 字体图集为 3628×3824 的 BC3/DXT5 DDS，无 mipmap。
- 索引修复修改 53 条路由和 65 个字节，不改变 DDS 图集。
- “庞”使用 U+8907 / record 2631，字形限制在安全框
  `(200,3030)-(248,3073)`。
- `GAME6.DAT` 回封保持官方 427 个 Oodle 块的数量、大小和边界。

## 安全与许可

- 本项目与 TT Games、Warner Bros. Games、Lucasfilm、Disney 或 LEGO Group 无关联。
- 请勿提交或分发完整游戏资源、游戏 EXE、Oodle DLL 或官方本地化文本。
- 安装器不会修改游戏 EXE。
- 字形来自 Noto Sans CJK，遵循 SIL Open Font License 1.1。
