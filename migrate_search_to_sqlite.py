"""
将提取的职位数据迁移到SQLite数据库
"""

import json
import sqlite3
import re
from pathlib import Path
from datetime import datetime


def parse_location(location_str):
    """解析地点字符串，返回 city, state, location_type"""
    city = ""
    state = ""
    location_type = "On-site"  # 默认

    if not location_str:
        return city, state, location_type

    # 解析 location_type: "On-site", "Remote", "Hybrid", "Hybrid (On-site)"
    type_patterns = [r"\((Remote|Hybrid|On-site)\)", r"(Remote|Hybrid|On-site)"]

    for pattern in type_patterns:
        match = re.search(pattern, location_str, re.IGNORECASE)
        if match:
            location_type = match.group(1) if match.group(1) else match.group(0)
            location_str = re.sub(pattern, "", location_str).strip()
            break

    # 清理剩余部分
    location_str = location_str.strip().rstrip(",").strip()

    # 解析 City, ST 格式
    city_state_match = re.match(r"^([^,]+),\s*([A-Z]{2})", location_str)
    if city_state_match:
        city = city_state_match.group(1).strip()
        state = city_state_match.group(2).strip()
    else:
        # 如果没有逗号分隔，整个可能是城市或特殊格式
        if location_str:
            city = location_str

    return city, state, location_type


def main():
    # 加载JSON数据
    json_file = Path(__file__).parent / "data" / "linkedin_jobs_search_extracted.json"
    db_file = Path(__file__).parent / "data" / "jobs.db"

    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    jobs = data["jobs"]
    print(f"加载 {len(jobs)} 个职位")

    # 连接数据库
    conn = sqlite3.connect(db_file)
    cur = conn.cursor()

    # 统计
    inserted = 0
    skipped = 0
    errors = 0

    for job in jobs:
        try:
            # 解析地点
            city, state, location_type = parse_location(job.get("location", ""))

            # 准备插入数据
            scraped_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

            cur.execute(
                """
                INSERT OR REPLACE INTO jobs 
                (id, source, source_url, job_title, company_name, location_type, city, state, country, scraped_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    job["id"],
                    "linkedin",
                    job["url"],
                    job["title"][:200] if job["title"] else "",
                    job["company"][:100] if job["company"] else "",
                    location_type,
                    city[:50] if city else "",
                    state[:2] if state else "",
                    "US",
                    scraped_at,
                ),
            )

            inserted += 1

        except Exception as e:
            errors += 1
            print(f"Error inserting {job.get('id')}: {e}")

    # 更新FTS索引
    cur.execute("""
        INSERT INTO jobs_fts(jobs_fts) VALUES('rebuild')
    """)

    conn.commit()

    # 验证
    cur.execute("SELECT COUNT(*) FROM jobs")
    total = cur.fetchone()[0]

    print(f"\n完成!")
    print(f"  新增: {inserted}")
    print(f"  跳过: {skipped}")
    print(f"  错误: {errors}")
    print(f"  数据库总记录: {total}")

    # 显示示例
    print("\n示例记录:")
    cur.execute("SELECT job_title, company_name, city, state, location_type FROM jobs LIMIT 5")
    for row in cur.fetchall():
        print(f"  {row[1][:20]:20} | {row[0][:30]:30} | {row[2]}, {row[3]} ({row[4]})")

    conn.close()


if __name__ == "__main__":
    main()
