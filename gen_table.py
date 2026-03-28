import sqlite3
import json
from datetime import datetime
from pathlib import Path

# 生成时间戳
GENERATED_AT = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "jobs.db"
HTML_PATH = Path(__file__).parent / "jobs_table.html"

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("""
SELECT 
    job_title,
    company_name,
    city,
    state,
    employment_type,
    salary_currency,
    salary_min,
    salary_max,
    salary_interval,
    posted_date,
    description_text
FROM jobs
ORDER BY posted_date DESC, company_name ASC
""")

jobs = []
for row in cur.fetchall():
    jobs.append(
        {
            "job_title": row[0],
            "company_name": row[1],
            "city": row[2],
            "state": row[3],
            "employment_type": row[4],
            "salary_currency": row[5],
            "salary_min": row[6],
            "salary_max": row[7],
            "salary_interval": row[8],
            "posted_date": row[9],
            "description_text": row[10],
        }
    )

conn.close()

# Generate HTML
html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LinkedIn 职位列表 - 分页展示</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 15px; }}
        .container {{ max-width: 99vw; margin: 0 auto; }}
        h1 {{ text-align: center; color: #333; margin-bottom: 15px; font-size: 1.6rem; }}
        .stats {{ text-align: center; color: #666; margin-bottom: 15px; font-size: 14px; }}
        table {{ width: 100%; background: white; border-collapse: collapse; box-shadow: 0 1px 3px rgba(0,0,0,0.12); border-radius: 8px; overflow: hidden; }}
        th {{ background: #0077b5; color: white; padding: 10px 6px; text-align: left; font-weight: 500; font-size: 0.8rem; position: sticky; top: 0; z-index: 10; }}
        td {{ padding: 8px 6px; border-bottom: 1px solid #eee; font-size: 0.8rem; vertical-align: top; max-width: 300px; }}
        tr:hover {{ background: #f8f9fa; }}
        .title {{ font-weight: 600; color: #0077b5; }}
        .company {{ color: #333; }}
        .location {{ color: #666; }}
        .salary {{ color: #2e7d32; font-weight: 500; white-space: nowrap; }}
        .type {{ display: inline-block; padding: 2px 6px; border-radius: 12px; font-size: 0.7rem; background: #e3f2fd; color: #1976d2; }}
        .date {{ color: #999; font-size: 0.75rem; white-space: nowrap; }}
        .desc {{ font-size: 0.75rem; color: #555; line-height: 1.4; max-height: 60px; overflow: hidden; text-overflow: ellipsis; cursor: pointer; }}
        .desc.expanded {{ max-height: none; }}
        .pagination {{ display: flex; justify-content: center; align-items: center; gap: 8px; margin-top: 15px; flex-wrap: wrap; }}
        .pagination button {{ padding: 8px 16px; border: 1px solid #ddd; background: white; cursor: pointer; border-radius: 4px; font-size: 14px; }}
        .pagination button:hover:not(:disabled) {{ background: #0077b5; color: white; border-color: #0077b5; }}
        .pagination button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
        .pagination .info {{ padding: 8px 16px; color: #666; }}
        .page-numbers {{ display: flex; gap: 4px; }}
        .page-numbers button {{ min-width: 40px; }}
        .page-numbers button.active {{ background: #0077b5; color: white; border-color: #0077b5; }}
        .show-more {{ color: #0077b5; }}
        .show-more:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📋 LinkedIn 职位列表 (含JD)</h1>
        <div class="stats" id="stats">共 171 个职位 · 更新时间：{GENERATED_AT}</div>
        <table>
            <thead>
                <tr>
                    <th style="width:180px">职位名称</th>
                    <th style="width:130px">公司</th>
                    <th style="width:80px">地点</th>
                    <th style="width:90px">薪资</th>
                    <th style="width:50px">类型</th>
                    <th style="width:70px">发布日期</th>
                    <th>职位描述</th>
                </tr>
            </thead>
            <tbody id="tableBody"></tbody>
        </table>
        <div class="pagination">
            <button id="prevBtn" onclick="prevPage()">上一页</button>
            <div class="page-numbers" id="pageNumbers"></div>
            <button id="nextBtn" onclick="nextPage()">下一页</button>
            <span class="info" id="pageInfo"></span>
        </div>
    </div>
    <script>
        const jobsData = {json.dumps(jobs, ensure_ascii=False)};
        const pageSize = 15;
        let currentPage = 1;
        let totalPages = Math.ceil(jobsData.length / pageSize);

        function toggleDesc(el) {{
            el.classList.toggle('expanded');
            el.innerHTML = el.classList.contains('expanded') 
                ? escapeHtml(el.dataset.full) 
                : escapeHtml(el.dataset.full).substring(0, 200) + '... <span class="show-more">展开</span>';
        }}

        function renderTable() {{
            const start = (currentPage - 1) * pageSize;
            const end = start + pageSize;
            const pageJobs = jobsData.slice(start, end);
            const tbody = document.getElementById('tableBody');
            tbody.innerHTML = pageJobs.map(job => {{
                const salary = formatSalary(job);
                const type = formatType(job.employment_type);
                const date = formatDate(job.posted_date);
                const desc = job.description_text || '-';
                const shortDesc = desc.length > 200 
                    ? desc.substring(0, 200) + '... <span class="show-more">展开</span>' 
                    : desc;
                const escapedFull = escapeHtml(desc).replace(/"/g, '&quot;');
                return `<tr>
                    <td class="title">${{escapeHtml(job.job_title)}}</td>
                    <td class="company">${{escapeHtml(job.company_name)}}</td>
                    <td class="location">${{escapeHtml(job.city)}}, ${{escapeHtml(job.state)}}</td>
                    <td class="salary">${{salary}}</td>
                    <td><span class="type">${{type}}</span></td>
                    <td class="date">${{date}}</td>
                    <td class="desc" data-full="${{escapedFull}}" onclick="toggleDesc(this)">${{shortDesc}}</td>
                </tr>`;
            }}).join('');
            document.getElementById('prevBtn').disabled = currentPage === 1;
            document.getElementById('nextBtn').disabled = currentPage === totalPages;
            document.getElementById('pageInfo').textContent = `第 ${{currentPage}} / ${{totalPages}} 页`;
        }}

        function renderPageNumbers() {{
            const container = document.getElementById('pageNumbers');
            let html = '';
            const maxVisible = 5;
            let start = Math.max(1, currentPage - Math.floor(maxVisible / 2));
            let end = Math.min(totalPages, start + maxVisible - 1);
            if (end - start < maxVisible - 1) start = Math.max(1, end - maxVisible + 1);
            for (let i = start; i <= end; i++) {{
                html += `<button onclick="goToPage(${{i}})" class="${{i === currentPage ? 'active' : ''}}">${{i}}</button>`;
            }}
            container.innerHTML = html;
        }}

        function prevPage() {{ if (currentPage > 1) {{ currentPage--; renderTable(); renderPageNumbers(); }} }}
        function nextPage() {{ if (currentPage < totalPages) {{ currentPage++; renderTable(); renderPageNumbers(); }} }}
        function goToPage(page) {{ currentPage = page; renderTable(); renderPageNumbers(); }}

        function formatSalary(job) {{
            if (job.salary_min && job.salary_max) {{
                const currency = job.salary_currency === 'USD' ? '$' : (job.salary_currency || '');
                const interval = job.salary_interval === 'HOUR' ? '/小时' : (job.salary_interval === 'YEAR' ? '/年' : '');
                return `${{currency}}${{job.salary_min}}-${{job.salary_max}}${{interval}}`;
            }}
            return '-';
        }}

        function formatType(type) {{
            const types = {{ 'INTERNSHIP': '实习', 'FULL_TIME': '全职', 'PART_TIME': '兼职', 'CONTRACT': '合同', 'TEMPORARY': '临时' }};
            return types[type] || type || '-';
        }}

        function formatDate(dateStr) {{
            if (!dateStr) return '-';
            const date = new Date(dateStr);
            return `${{date.getFullYear()}}-${{String(date.getMonth()+1).padStart(2,'0')}}-${{String(date.getDate()).padStart(2,'0')}}`;
        }}

        function escapeHtml(text) {{
            if (!text) return '';
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }}

        document.getElementById('stats').textContent = `共 ${{jobsData.length}} 个职位 · 更新时间：{GENERATED_AT} · 每页显示 ${{pageSize}} 条，点击描述可展开`;
        renderTable();
        renderPageNumbers();
    </script>
</body>
</html>"""

with open(HTML_PATH, "w", encoding="utf-8") as f:
    f.write(html)

print(f"Generated HTML with {len(jobs)} jobs and descriptions")
