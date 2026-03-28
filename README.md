# JobFetcher - LinkedIn 土木/环境工程职位爬虫

使用 **opencli** 爬取 LinkedIn 职位列表，**XCrawl** 获取职位详情（JD）。

## 项目概述

从 LinkedIn 爬取美国地区土木工程和环境工程职位，存储到 SQLite 数据库，支持全文搜索。

- **搜索关键词**：`civil engineer OR environmental engineer`
- **搜索地区**：`United States`
- **时间过滤**：最近一周发布的职位

## 工作流程

```
┌─────────────────────────────────────────────────────────────────┐
│  步骤 1：scrape_all_jobs.py (opencli)                          │
│  - opencli linkedin search 获取结构化职位列表                    │
│  - 提取：url, title, company, location, listed date              │
│  - 自动去重（基于 LinkedIn Job ID）                              │
│  - 输出：data/linkedin_jobs_*.json                              │
└─────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────┐
│  步骤 2：migrate_to_sqlite.py                                   │
│  - JSON → 结构化 SQLite schema                                  │
│  - 解析 location → city / state / location_type                 │
│  - 创建 FTS5 全文搜索索引                                        │
│  - 输出：data/jobs.db                                           │
└─────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────┐
│  步骤 3：jd_fetch.py (XCrawl)                                   │
│  - 读取 source_url 列表                                         │
│  - XCrawl Scrape API 获取完整 JD（js_render + markdown）        │
│  - extract_jd_from_markdown() 提取 JD 文本                      │
│  - 更新 jobs.description_text 字段                              │
│  - 重建 FTS5 索引                                               │
└─────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────┐
│  步骤 4：gen_table.py                                           │
│  - 从 jobs.db 读取所有职位                                       │
│  - 排序：posted_date DESC + company_name ASC                    │
│  - 输出：jobs_table.html（分页，含 JD 展开）                    │
└─────────────────────────────────────────────────────────────────┘
```

## 快速开始

```bash
cd D:/opencode/jobfetcher

# 1. 配置 opencli（确保 Chrome 扩展已连接）
opencli doctor

# 2. 配置 XCrawl API Key（~/.xcrawl/config.json）
#    {"XCRAWL_API_KEY": "your_key_here"}

# 3. 查看数据库状态
python jd_fetch.py --status

# 4. 抓取职位列表（opencli）
python scrape_all_jobs.py \
  --keywords "civil engineer OR environmental engineer" \
  --location "United States" \
  --max-results 100

# 5. 迁移到 SQLite（自动执行，也可单独运行）
python migrate_to_sqlite.py

# 6. 获取缺失的 JD（XCrawl）
python jd_fetch.py --fetch

# 7. 生成 HTML 报告
python gen_table.py
```

## 推荐：一键运行

```bash
# 完整流水线（自动执行所有步骤）
python run_pipeline.py --all --html
```

## 单独步骤

```bash
# 仅抓取职位列表
python scrape_all_jobs.py --keywords "civil engineer OR environmental engineer" --location "United States" --max-results 100

# 仅迁移 JSON → SQLite
python migrate_to_sqlite.py

# 查看 JD 状态
python jd_fetch.py --status

# 获取缺失 JD
python jd_fetch.py --fetch

# 重建 FTS5 索引
python jd_fetch.py --rebuild-fts

# 生成 HTML 报告
python gen_table.py

# 查看数据库统计
python run_pipeline.py --check
```

## 文件结构

```
jobfetcher/
├── README.md                  # 本文件
├── requirements.txt           # Python 依赖
├── pyproject.toml            # 项目配置
├── run_pipeline.py           # 流水线协调器
├── scrape_all_jobs.py        # 步骤1：opencli 抓取
├── migrate_to_sqlite.py      # 步骤2：JSON → SQLite
├── jd_fetch.py               # 步骤3：JD 获取（XCrawl）
├── xcrawl_client.py          # XCrawl API 封装
├── gen_table.py              # 步骤4：生成 HTML
├── backfill_dates.py         # 回填发布日期
├── data/
│   ├── jobs.db               # SQLite 数据库
│   └── linkedin_jobs_*.json  # JSON 缓存
└── jobs_table.html           # HTML 报告
```

## 数据库结构

### 主表 jobs

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT | LinkedIn 完整 URL |
| `source` | TEXT | 数据来源，默认 'linkedin' |
| `source_url` | TEXT | 完整 LinkedIn URL |
| `job_title` | TEXT | 职位名称 |
| `company_name` | TEXT | 公司名称 |
| `location_type` | TEXT | 'onsite' / 'remote' / 'hybrid' |
| `city` | TEXT | 城市 |
| `state` | TEXT | 州（2字母缩写） |
| `country` | TEXT | 国家，默认 'US' |
| `employment_type` | TEXT | 'INTERNSHIP' / 'FULL_TIME' 等 |
| `salary_currency` | TEXT | 货币，如 'USD' |
| `salary_min` | REAL | 最低薪资 |
| `salary_max` | REAL | 最高薪资 |
| `salary_interval` | TEXT | 'HOUR' / 'YEAR' 等 |
| `description_text` | TEXT | 职位描述（纯文本） |
| `posted_date` | TEXT | ISO 日期字符串 |
| `scraped_at` | TEXT | 爬取时间 |

### 全文搜索表 jobs_fts

```sql
CREATE VIRTUAL TABLE jobs_fts USING fts5(
    job_title, company_name, city, state, description_text,
    content='jobs', content_rowid='rowid'
);
```

## 数据库使用示例

```python
import sqlite3

conn = sqlite3.connect("data/jobs.db")

# 查看所有职位
count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
print(f"总职位数: {count}")

# 德克萨斯州的土木工程实习
rows = conn.execute("""
    SELECT job_title, company_name, city
    FROM jobs
    WHERE state = 'TX'
      AND employment_type = 'INTERNSHIP'
      AND (job_title LIKE '%civil%' OR job_title LIKE '%environmental%')
    ORDER BY company_name
""").fetchall()

# 全文搜索
rows = conn.execute("""
    SELECT job_title, company_name, city,
           snippet(jobs_fts, 4, '<b>', '</b>', '...', 20) as context
    FROM jobs_fts
    JOIN jobs ON jobs.rowid = jobs_fts.rowid
    WHERE jobs_fts MATCH 'storm water OR wastewater'
    LIMIT 10
""").fetchall()

# 按公司统计
top_companies = conn.execute("""
    SELECT company_name, COUNT(*) as cnt
    FROM jobs GROUP BY company_name
    ORDER BY cnt DESC LIMIT 5
""").fetchall()

# 各州职位分布
by_state = conn.execute("""
    SELECT state, COUNT(*) as cnt
    FROM jobs WHERE state != ''
    GROUP BY state ORDER BY cnt DESC
""").fetchall()
```

## JD 获取（XCrawl）

JD 获取使用 `xcrawl_client.py`，内部逻辑：

```
fetch_jd(url)
  ├── wait_before_request()          # 随机延迟 1.5-3s 防限流
  ├── scrape_url_with_fallback(url)  # sync → async 自动切换
  │     └── XCrawl Scrape API       # js_render + markdown 输出
  └── extract_jd_from_markdown()     # 从 markdown 提 JD 文本
        ├── 匹配标记：Job Description / About the job / Responsibilities...
        └── 截断：Similar jobs / Seniority level 等
```

### xcrawl_client.py 主要函数

```python
from xcrawl_client import fetch_jd, fetch_jd_batch

# 单个 JD
jd_text = fetch_jd("https://www.linkedin.com/jobs/view/123456789")

# 批量 JD
results = fetch_jd_batch(urls, stop_on_error=False)
```

## HTML 报告

生成交互式分页表格 `jobs_table.html`：

- 分页显示（每页 15 条）
- 点击 JD 可展开/收起
- 按发布日期倒序排列

```bash
# 重新生成
python gen_table.py
```

## 数据状态

截至 2026-03-28：

| 指标 | 数值 |
|------|------|
| 总职位数 | 198 |
| 有 JD | 198 (100%) |
| FTS5 索引 | 198 |

## 定时任务

```bash
# crontab -e

# 每天早上 10 点：完整流水线
0 10 * * * cd /home/user/jobfetcher && python run_pipeline.py --all --html >> logs/pipeline.log 2>&1

# 每天早上 11 点：仅生成 HTML（数据已存在）
0 11 * * * cd /home/user/jobfetcher && python gen_table.py >> logs/html.log 2>&1
```

## 架构说明

### 为什么 opencli 负责职位列表？

| opencli | Playwright |
|---------|------------|
| 结构化 JSON 输出 | DOM 解析复杂 |
| 无需 Cookie/登录 | 需要维护 Cookie |
| 调用简单 | 浏览器管理复杂 |
| 不易被封 | 易触发反爬 |

### 为什么 XCrawl 负责 JD？

| XCrawl | opencli |
|--------|---------|
| 支持 JS 渲染等待 | 适合列表不适合详情 |
| markdown 格式统一 | 返回原始 HTML |
| 异步 + 轮询 | 同步调用 |

### 关键文件对应关系

| 任务 | 工具/文件 |
|------|-----------|
| 职位列表 | opencli `linkedin search` |
| 去重 | `normalize_url()` — 按 Job ID |
| 数据转换 | `migrate_to_sqlite.py` |
| JD 获取 | `xcrawl_client.py` |
| JD 文本提取 | `extract_jd_from_markdown()` |
| 全文搜索 | SQLite FTS5 |

## 注意事项

- **opencli** 需要 Chrome 扩展已连接，运行 `opencli doctor` 检查
- **XCrawl** 需要配置 `~/.xcrawl/config.json`
- SQLite 是主存储，JSON 是中间格式
- 去重基于 LinkedIn Job ID，支持新旧两种 URL 格式
