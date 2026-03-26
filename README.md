# JobFetcher - LinkedIn 土木/环境工程职位爬虫

使用 Playwright MCP（浏览器自动化 + 已登录会话）爬取 LinkedIn 上美国地区的土木工程和环境工程职位（包括全职和实习）。

## 搜索配置

- **搜索关键词**：`civil engineering and environmental engineering jobs in the United States`
- **搜索地区**：United States
- **时间过滤**：最近 30 天内发布的职位（`f_TPR=r2592000`）

## 工作流程

```
python run_pipeline.py --step all        # 完整流水线（推荐）
python run_pipeline.py --step scrape     # 仅步骤 1：爬取
python run_pipeline.py --step migrate    # 仅步骤 3：JSON → SQLite

# --step all 内部流程：
┌─────────────────────────────────────────────────────────────────┐
│  步骤 1：爬取职位 (scrape_all_jobs.py)                            │
│  - 使用 Playwright MCP 访问 LinkedIn 搜索结果                    │
│  - 搜索关键词："civil engineering and environmental engineering │
│    jobs in the United States"，地区："United States"            │
│  - 提取：职位名称、公司、地点、URL、发布日期                      │
│    （从 JSON-LD datePosted 字段获取真实 ISO 日期）               │
│  - 处理分页（最多 22 页，每页 25 个职位）                        │
│  - 与 SQLite 数据库和当前 JSON 文件进行去重                      │
│  - 输出：data/linkedin_jobs_YYYYMMDD_new.json                   │
│  - ✅ 完成自动迁移到 SQLite                                      │
└─────────────────────────────────────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│  步骤 2：补充职位描述 (MCP webfetch — 手动或脚本)                │
│  - 使用 webfetch 工具从 LinkedIn 职位 URL 获取描述文本          │
│  - 解析 "Job Description" / "About the job" 部分                │
│  - 在 "Seniority level"、"Similar jobs"、"Referrals" 处截断     │
│  -原地更新 JSON 中的 description 字段                           │
│  - 备选方案：jd_fallback.py / jd_fallback2.py                   │
│  - 所有描述补充完成后：python jd_fetch.py --migrate            │
└─────────────────────────────────────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│  步骤 3：迁移到 SQLite (migrate_to_sqlite.py)                    │
│  - scrape_all_jobs.py 完成后自动运行                            │
│  - 将扁平 JSON 转换为结构化 SQLite 模式                          │
│  - 自动解析：城市/州、职位类型、薪资、日期                        │
│  - 创建 FTS5 全文搜索索引                                        │
│  - 输出：data/jobs.db (SQLite)                                  │
└─────────────────────────────────────────────────────────────────┘
```

## 文件结构

```
jobfetcher/
├── README.md                  # 本文件
├── requirements.txt           # Python 依赖
├── pyproject.toml            # 项目配置
├── run_pipeline.py           # ✅ 主协调器（请使用此文件！）
├── scrape_all_jobs.py        # 步骤 1：LinkedIn 爬虫 (Playwright MCP)
├── jd_fetch.py               # 步骤 2：补充 JD + 自动迁移
├── jd_fallback.py            # 步骤 2b：备选 JD 获取策略
├── jd_fallback2.py           # 步骤 2b：额外备选策略
├── backfill_dates.py         # 回填真实发布日期
├── migrate_to_sqlite.py      # JSON → SQLite 迁移 + FTS（自动调用）
├── playwright_extractor.py   # Playwright 浏览器工具
├── hooks/                    # Git hooks
│   └── post-commit           # 每次提交后自动推送到 GitHub
├── src/                      # 原始 jobfetcher 包
│   └── jobfetcher/
│       ├── api/              # FastAPI REST API
│       ├── cli/              # 命令行接口
│       ├── models/           # 数据模型 (JobListing 等)
│       ├── scrapers/         # 平台爬虫 (LinkedIn 等)
│       └── storage/          # SQLite、JSON、CSV 后端
└── data/
    ├── jobs.db               # ✅ SQLite 数据库（持久化存储）
    └── linkedin_jobs_*.json  # JSON 源（导入 SQLite 用）
```

## SQLite 数据库结构

```sql
-- 主表
CREATE TABLE jobs (
    id              TEXT PRIMARY KEY,
    source          TEXT NOT NULL DEFAULT 'linkedin',
    source_url      TEXT UNIQUE NOT NULL,
    job_title       TEXT NOT NULL,
    company_name    TEXT NOT NULL,
    company_url     TEXT,
    location_type   TEXT,         -- 'onsite', 'remote', 'hybrid'
    city            TEXT,
    state           TEXT,         -- 2字母州缩写，如 'TX'
    country         TEXT DEFAULT 'US',
    postal_code     TEXT,
    employment_type TEXT,         -- 'INTERNSHIP', 'FULL_TIME' 等
    salary_currency TEXT,
    salary_min      REAL,
    salary_max      REAL,
    salary_interval TEXT,        -- 'HOUR', 'YEAR' 等
    description_text TEXT,
    description_html TEXT,
    requirements_json TEXT,
    posted_date     TEXT,         -- ISO 日期字符串
    expiry_date     TEXT,
    scraped_at      TEXT NOT NULL,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX idx_jobs_source      ON jobs(source);
CREATE INDEX idx_jobs_title       ON jobs(job_title);
CREATE INDEX idx_jobs_state        ON jobs(state);
CREATE INDEX idx_jobs_company      ON jobs(company_name);
CREATE INDEX idx_jobs_posted_date  ON jobs(posted_date);
CREATE INDEX idx_jobs_employment   ON jobs(employment_type);

-- 全文搜索 (FTS5)
CREATE VIRTUAL TABLE jobs_fts USING fts5(
    job_title, company_name, city, state, description_text,
    content='jobs', content_rowid='rowid'
);
```

## SQLite 使用示例

```python
import sqlite3

conn = sqlite3.connect("data/jobs.db")

# 查看所有职位
for row in conn.execute("SELECT COUNT(*) FROM jobs"):
    print(f"总职位数: {row[0]}")

# 德克萨斯州的土木工程实习生
for row in conn.execute("""
    SELECT job_title, company_name, city
    FROM jobs
    WHERE state = 'TX'
      AND employment_type = 'INTERNSHIP'
      AND (job_title LIKE '%civil%' OR job_title LIKE '%environmental%')
    ORDER BY company_name
"""):
    print(row)

# 全文搜索
for row in conn.execute("""
    SELECT job_title, company_name, city, snippet(jobs_fts, 4, '<b>', '</b>', '...', 20) as context
    FROM jobs_fts
    JOIN jobs ON jobs.rowid = jobs_fts.rowid
    WHERE jobs_fts MATCH 'storm water OR wastewater'
    LIMIT 10
"""):
    print(f"{row[0]} @ {row[1]} ({row[2]})")
    print(f"  {row[3]}")

# 按公司统计职位数量
print(conn.execute("SELECT company_name, COUNT(*) FROM jobs GROUP BY company_name ORDER BY COUNT(*) DESC LIMIT 5").fetchall())

# 各州职位分布
print(conn.execute("SELECT state, COUNT(*) FROM jobs WHERE state != '' GROUP BY state ORDER BY COUNT(*) DESC").fetchall())
```

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# ── 一键流水线（推荐）────────────────────────────────────────────
python run_pipeline.py --step all    # 完整流程：爬取 → 自动迁移

# ── 分步骤执行 ─────────────────────────────────────────────────
python run_pipeline.py --step scrape  # 爬取职位（需要 Playwright MCP）
python jd_fetch.py                   # 通过 MCP webfetch 补充 JD（手动）
python run_pipeline.py --step migrate  # JSON → SQLite + FTS

# ── 查询数据库 ────────────────────────────────────────────────
python -c "
import sqlite3
conn = sqlite3.connect('data/jobs.db')
print('总职位数:', conn.execute('SELECT COUNT(*) FROM jobs').fetchone()[0])
print('各公司职位数:', conn.execute('SELECT company_name, COUNT(*) FROM jobs GROUP BY company_name ORDER BY COUNT(*) DESC LIMIT 5').fetchall())
"

# ── 回填日期 ──────────────────────────────────────────────────
python backfill_dates.py --fallback
```

## 数据格式（JSON legacy）

```json
{
  "title": "Civil Engineering Intern",
  "company": "WSP in the U.S.",
  "location": "Houston, TX (On-site)",
  "url": "https://www.linkedin.com/jobs/view/4384037771",
  "source": "linkedin",
  "job_type": "Internship",
  "posted_date": "1 week ago",
  "description": "完整职位描述..."
}
```

## 注意事项

- **请使用 `run_pipeline.py`** 作为主入口，它负责完整流水线。
- LinkedIn 需要已登录会话。请使用已登录 LinkedIn 的 Playwright MCP 连接。
- `f_TPR=r2592000` 过滤为最近 30 天内发布的职位。
- `scrape_all_jobs.py` 完成后自动迁移到 SQLite — 爬取后无需手动操作。
- 通过 MCP webfetch 补充 JD 后，运行 `python jd_fetch.py --migrate` 推送到 SQLite。
- 如 LinkedIn 阻止直接访问 JD，可对职位 URL 使用 `webfetch` — 可绕过 JS 渲染阻止。
- SQLite 是主要存储。JSON 是导入 SQLite 用的可移植交换格式。
- `backfill_dates.py --fallback` 将相对日期转换为 ISO 日期（以爬取日期为参考）。

## 当前数据状态

截至 2026-03-26，SQLite 数据库 (`data/jobs.db`) 包含：

| 指标 | 数值 |
|------|------|
| 总职位数 | 3 |
| 数据完整度 | 部分字段缺失 |

### 字段完整度

| 字段 | 完整率 | 说明 |
|------|--------|------|
| `job_title` | 100% | ✅ |
| `company_name` | 0% | ⚠️ 待补充 |
| `city` / `state` | 100% | ✅ 部分解析异常 |
| `employment_type` | 100% | ✅ |
| `description_text` | 66% | ⚠️ 部分职位有 JD |
| `posted_date` | 0% | ⚠️ 待补充 |

### 补充职位详情

如需补充完整信息，运行：

```bash
# 继续 enrichment（会复用已有数据，逐步追加）
python enrich_jobs.py

# 指定数量测试
python enrich_jobs.py 10
```

### 最新抓取数据

- `scrape_linkedin_mcp.py` - 快速抓取职位链接（60 个唯一职位）
- `enrich_jobs.py` - 补充公司、地点、描述、发布日期
