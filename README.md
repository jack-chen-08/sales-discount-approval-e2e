# 招商闭环 · 超权限折扣审批与绕过审批拦截（E2E 测试用例集）

本仓是「会员空间平台 · 招商闭环」折扣审批链路的**可执行测试用例集 + 配套参考实现**。
用例覆盖客户验收条款的四条链路分支，全部可一键复跑，并附运行报告与截图。

- 工单：**S4-E2E-035 会员空间平台 · 招商闭环：超权限折扣审批与绕过审批的拦截用例**
- 交付形态：Python 3.11+ / FastAPI 参考实现 + pytest 用例（httpx 接口层 + Playwright UI 层）
- 数据：全部虚构（公司名、人名、金额均为编造），不含任何真实企业或个人数据

---

## 1. 一分钟跑起来

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium      # 只跑接口用例时可不装
bash run_tests.sh                          # 期望：39 passed
```

只跑接口层（不需要浏览器）：

```bash
python -m pytest tests -q --ignore=tests/ui      # 35 passed
```

复用手边已开着的浏览器（含登录态、无网下载浏览器时）：

```bash
PW_CDP=http://127.0.0.1:9222 python -m pytest tests/ui -q
```

手动起服务看工作台：

```bash
uvicorn app.main:app --port 8000
# http://127.0.0.1:8000/workbench?opportunity_id=44444444-4444-4444-8444-444444444441&as_user=33333333-3333-4333-8333-333333333332
```

`as_user` 换 `...3331`（顾问）/ `...3332`（运营主管）/ `...3333`（会所负责人）即可切换身份视角。

---

## 2. 目录结构

```
app/
  policy.py            折扣→审批角色的唯一判据（9 折为分界线），页面与接口共用
  models.py            SQLAlchemy 2.0 模型（业务表含 id/org_id/site_id/created_at/created_by/updated_at/deleted_at）
  service.py           审批提交、审批决策、报价单生成的唯一执行路径；企业微信卡片回调
  main.py              FastAPI 装配：/api 与 /api/v1 双前缀、/workbench 页面、/workbench/decision 表单
  seed.py              确定性虚构测试数据（固定 UUID，截图可复现）
  templates/workbench.html  招商工作台（按角色渲染审批入口）
tests/
  test_branch1_approval_gate.py       分支①：审批前 409 → 审批后可出单（工作台 + 企微卡片两条路径）
  test_branch2_role_escalation.py     分支②：低于 9 折只有会所负责人能批，运营主管 403
  test_branch3_bypass_attempts.py     分支③：四种绕过尝试全部拦截，错误码可区分
  test_branch4_rejection.py           分支④：驳回后不可出单、意见回填、可重新发起
  test_workbench_form.py              页面按钮提交与接口同一判据（越权同样 403 并在页面回显）
  test_rules_and_boundaries.py        原价免审、折扣区间、组织隔离、/api 与 /api/v1 行为一致
  ui/test_workbench_ui.py             工作台渲染断言 + 四张截图
docs/
  运行报告.md          实测环境、命令、结果、截图说明
  test_output.txt      原始 pytest -v 输出
  screenshots/         四张工作台截图（角色视角 / 驳回意见 / 合同附件）
```

---

## 3. 验收条款 → 用例对照

| 客户验收条款 | 覆盖用例 | 断言要点 |
|:--|:--|:--|
| 四条链路分支都能跑通，结果符合预期 | `test_branch1..4`（共 23 条） | 每支分支独立成型、互不依赖执行顺序 |
| 两个绕过场景都被拦住，状态码与错误码都断言 | `test_branch3_bypass_attempts.py` | 伪造审批号 `409 APPROVAL_NOT_FOUND`；跨商机 `409 APPROVAL_SCOPE_MISMATCH`；改折扣 `409 QUOTE_APPROVAL_REQUIRED(reason=discount_changed_after_approval)`；重放 `409 APPROVAL_ALREADY_CONSUMED` |
| 审批前生成报价单 → 409 + `QUOTE_APPROVAL_REQUIRED` | `test_branch1_approval_gate.py::test_02_quote_blocked_before_approval`、`::test_03_quote_blocked_without_any_approval_id` | 状态码 + 错误码 + `required_role` 一并断言 |
| 低于 9 折时只有会所负责人能批，运营主管看不到按钮 | `test_branch2_role_escalation.py`、`tests/ui/test_workbench_ui.py::test_01/02` | 接口 403 + 页面无按钮（双视图一致，防「UI 藏了、接口能过」） |
| 审批记录进入合同附件 | `test_branch1::test_05_approval_record_enters_contract_attachments`、`test_branch2::test_05_club_manager_record_in_contract_attachments`、UI `test_04_contract_attachment_listed_for_approved_quote` | 附件含审批人、折扣、时间、单号 |
| 驳回后报价单不可生成，驳回意见回到工作台 | `test_branch4_rejection.py::test_02/03`、UI `test_03_rejection_comment_is_shown_in_workbench` | `409 QUOTE_APPROVAL_REJECTED` + 意见文本在页面可见 |
| 套件可重复执行 | 全部用例 | 每用例独立内存库；UI 用例只读，不依赖执行顺序 |

---

## 4. 审批口径（唯一判据）

| 折扣 | 换算（万分位整数） | 审批角色 | 免审 |
|:--|:--|:--|:--|
| 10 折（原价） | 10000 | — | 是 |
| 9 折 | 9000 | `ops_supervisor` 运营主管 | 否 |
| 8.5 折 / 8 折 | 8500 / 8000 | `club_manager` 会所负责人 | 否 |

判据只有一份实现：`app/policy.py::required_role()`。页面渲染按钮与接口鉴权都调用它，
不存在「页面判断一套、接口判断另一套」的分叉。

金额一律以「分」存整数、折扣以「万分位整数」存（`9000` = 9 折），对外 JSON 再折算成小数，
杜绝 `0.85 * 100` 类浮点误差导致的审批绕过。

### 错误码表

| HTTP | code | 触发条件 |
|:--|:--|:--|
| 409 | `QUOTE_APPROVAL_REQUIRED` | 未提供审批号 / 审批未决 / 审批已失效 / 折扣与审批单不一致 |
| 409 | `APPROVAL_NOT_FOUND` | 审批号不存在（伪造） |
| 409 | `APPROVAL_SCOPE_MISMATCH` | 审批单属于另一商机（拿来主义绕过） |
| 409 | `APPROVAL_ALREADY_CONSUMED` | 同一审批单生成第二张报价单（重放） |
| 409 | `QUOTE_APPROVAL_REJECTED` | 审批单已驳回 |
| 409 | `APPROVAL_ALREADY_DECIDED` | 同一审批单二次决策 |
| 403 | `APPROVAL_FORBIDDEN_ROLE` | 当前角色不是该折扣要求的审批角色 |
| 403 | `ORG_ISOLATION_VIOLATION` | 跨组织操作 |
| 400 | `REJECT_COMMENT_REQUIRED` | 驳回未填意见 |
| 400 | `DISCOUNT_OUT_OF_RANGE` | 折扣不在 [5 折, 10 折] |

---

## 5. 依赖桩与对接点（替换成真实模块时只改这几处）

| 依赖模块 | 本仓的处理 | 真实环境替换点 |
|:--|:--|:--|
| S2-IAM 身份与组织 | `app/seed.py` 固定用户 + `org_id` 隔离；`as_user` 参数模拟登录态 | `main.py` 取当前用户的 3 处（`_current_user`），换成网关注入的身份头 |
| S3-SALES 商机/报价 | `Opportunity` / `Quote` 自建表，字段按工单描述最小实现 | `service.create_quote()` 落库前换成调 S3 报价接口；金额仍以分传 |
| 企业微信审批卡片 | `POST /api/integrations/wecom/approval-callback` 桩实现，HMAC-SHA256 校验 `signature` | 换成企业微信真实回调；密钥读 `WECOM_STUB_SECRET` 环境变量，**不进代码** |
| 合同附件 | `ContractAttachment` 表 + 审批通过时落一条记录 + `file_ref` 占位 | 换成合同服务的附件挂接接口，`file_ref` 换成真实文件标识 |
| 数据库 | 默认 SQLite（`DATABASE_URL` 环境变量可切 PostgreSQL 16） | 生产配置 `DATABASE_URL=postgresql+psycopg://...` |

---

## 6. 已知边界（照实写，避免误判）

1. **参考实现是最小闭环**：只实现折扣审批与报价单生成，不含会员空间招商的其他环节（合同签署、账单、佣金结算）。
2. **无并发压测**：审批并发（两人同时点批准）用 `status` 状态机保证不会双写，但未做行级锁与压测；生产需在 `SELECT ... FOR UPDATE` 上加锁。
3. **企业微信回调为桩**：只校验签名与角色，未接真实卡片模板与加密消息体。
4. **UI 用例依赖真实浏览器**：无浏览器时自动 `skip`（不伪装成通过），接口层 35 条仍然全覆盖。
5. **Playwright 跨栈注意事项**：浏览器在 Windows、服务在 WSL 时，浏览器必须用 WSL 对外 IP 访问（`PW_BASE_HOST` 可覆盖），否则 `127.0.0.1` 在两个网络栈里不是同一个地址。本仓 `tests/ui/conftest.py::_browser_host()` 已自动处理。

---

## 7. 安全

- 仓内无任何密钥、令牌、内网地址；企业微信桩密钥从环境变量读取，默认值仅用于本地测试。
- 全部测试数据虚构；无真实企业名称、手机号、合同金额。
- 依赖版本在 `requirements.txt` 中锁定。
