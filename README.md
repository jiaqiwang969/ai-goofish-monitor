# Goofish (Xianyu) MCP - Minimal Fork

这个 fork 只保留“动手能力”，目标是给 Codex 这种“强大脑”提供可调用的 MCP tools：

- 导入/写入闲鱼登录态 JSON（来自浏览器扩展导出）
- 搜索商品（返回结构化候选 + 链接）
- 打开商品详情页（返回描述/图片/卖家信息/原始字段）

是否购买、如何匹配采购清单、如何找替代品等决策，交给 MCP 客户端（Codex + skills）完成。

## 依赖

- Python 3.9+
- Playwright (Python)

## 零手动安装（推荐）

只要你把 goofish MCP 配到 `~/.codex/config.toml`，Codex 启动时会拉起 MCP server，
server 会在后台自动检查并安装（仅在缺失时才安装）：

- `pip install playwright`（用户目录）
- `playwright install chromium`

第一次可能需要几分钟下载浏览器；装好以后会自动跳过。

> 如需禁用：`GOOFISH_AUTO_SETUP=0`

```bash
pip install -r requirements.txt
playwright install chromium
```

### 一键安装（推荐，npx 方式）

如果你不想手动 pip / playwright install，可以直接运行：

```bash
npx -y --package github:jiaqiwang969/ai-goofish-monitor#main goofish-mcp-setup
```

## 最省事的登录方式（推荐：Playwright 打开真实浏览器，让你手动登录）

如果你不想装/加载浏览器扩展，直接用下面命令打开一个浏览器窗口，自己扫码/短信登录，然后回到终端按回车即可：

```bash
npx -y --package github:jiaqiwang969/ai-goofish-monitor#main goofish-mcp-login
```

它会把 Playwright 的 `storage_state` JSON 写到：

- `$GOOFISH_STATE_FILE`（如果你设置了）
- 否则 `~/.codex/goofish/xianyu_state.json`

## 登录态 JSON（推荐）

使用闲鱼登录态导出扩展获取 JSON 后，有两种方式提供给 MCP：

1) 直接保存到默认路径：`state/xianyu_state.json`
2) 或在 Codex 里调用 tool：`xianyu_write_login_state`（把 JSON 字符串写入本地文件）

默认状态文件路径可用环境变量覆盖：

- `GOOFISH_STATE_FILE=state/acc_1.json`

## 运行 MCP Server

### 方式 A：直接用 Python（本地开发推荐）

```bash
python3 -m goofish_mcp
```

### 方式 B：npx（像你现有的其它 MCP 一样）

仓库根目录提供了 `package.json` + `bin/goofish-mcp`，可用：

```bash
npx -y github:jiaqiwang969/ai-goofish-monitor#main
```

> 注意：`npx` 只是一个 launcher，真正执行的是 `python3 -m goofish_mcp`。

## 环境变量（常用）

- `GOOFISH_RUN_HEADLESS=false`：有时非无头更不容易触发风控
- `GOOFISH_BROWSER_CHANNEL=chrome`：可选，使用系统 Chrome（不设则用 Playwright 自带 Chromium）
- `GOOFISH_PYTHON=/path/to/python3`：npx launcher 用哪个 Python

## MCP Tools

- `xianyu_write_login_state(content, path?)`
- `xianyu_search(query, limit?, state_file?, headless?, proxy_server?)`
- `xianyu_get_listing(url, state_file?, headless?, proxy_server?, include_raw?)`
- `xianyu_healthcheck()`

## Codex 配置示例

把下面加到 `~/.codex/config.toml`：

```toml
[mcp_servers.goofish]
command = "npx"
args = ["-y", "--package", "github:jiaqiwang969/ai-goofish-monitor#main", "--", "goofish-mcp"]
startup_timeout_sec = 60
tool_timeout_sec = 3600

[mcp_servers.goofish.env]
GOOFISH_STATE_FILE = "/Users/jqwang/.codex/goofish/xianyu_state.json"
PYTHONPYCACHEPREFIX = "/tmp/pycache-goofish"
GOOFISH_AUTO_SETUP = "1"
# 可选：尽量让 npm/npx 安静一点，避免 stdout 污染（MCP stdio 只能输出 JSON）。
NO_UPDATE_NOTIFIER = "1"
npm_config_update_notifier = "false"
npm_config_loglevel = "error"
npm_config_fund = "false"
npm_config_audit = "false"
```
