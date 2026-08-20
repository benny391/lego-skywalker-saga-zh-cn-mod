# LEGO Star Wars: The Skywalker Saga 大陆简体中文 Mod 工具链

这是 Steam 版 **LEGO Star Wars: The Skywalker Saga** 大陆简体中文 Mod 的研究记录、转换脚本、字体处理工具、资源回封工具和结构验证器。

仓库只提供工具与技术文档，不包含游戏原始 DAT、官方本地化文本、游戏 EXE、Oodle DLL、解包字体、生成后的完整资源或其他受版权保护的游戏文件。使用者必须自行拥有合法游戏副本。

## 已验证技术路线

1. 从 `GAME.DAT` 定位并提取 `stuff/text/text.csv`。
2. 将官方繁体中文转换为大陆简体中文，并通过术语表进行语义修订。
3. 保留 ID、占位符、格式说明符、标签、转义序列和控制字符。
4. 使用运行时别名解决官方字体映射中缺少或异常的简体字。
5. 在 `font_chinese_nxg.ft2` 的既有字形槽中绘制 Noto Sans SC Regular 字形。
6. 保持 FT2 Unicode 映射、字形几何、文件大小和资源索引结构不变。
7. 使用游戏自带的 Oodle DLL 对 OODL 资源进行逐块回封；ZIPX 资源使用项目内实现回封。
8. 对生成资源重新提取并逐字节验证，然后制作固定哈希差分安装包。

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

## “飞船→飞葛”定向修复

`build_ship_alias_fix.py` 处理游戏运行时对“船”原生字形槽的异常取字：中文栏中的“船”被编码到一个未使用的内部别名槽，字体中该槽绘制为“船”。该处理保持 UTF-8 字节长度和全部文本结构不变。

## 法律与安全说明

- 本项目与 TT Games、Warner Bros. Games、Lucasfilm、Disney 或 LEGO Group 无关联。
- 不要提交或分发完整游戏资源、EXE、Oodle DLL 或官方文本数据。
- 修改前始终保留官方文件备份；Steam 更新或“验证游戏文件完整性”可能恢复官方文件。
- 字体字形来源 Noto Sans CJK，遵循 SIL Open Font License 1.1。
