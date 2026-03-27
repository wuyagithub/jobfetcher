"""
LinkedIn职位提取脚本
直接从bb-browser输出解析JSON
"""

import json
import subprocess
import time
from pathlib import Path

PROGRESS_FILE = Path(__file__).parent / "data" / "linkedin_search_progress.json"
OUTPUT_FILE = Path(__file__).parent / "data" / "linkedin_jobs_search_extracted.json"
BASE_URL = "https://www.linkedin.com/jobs/search/?keywords=civil+engineer+environmental+engineer+jobs+in+the+United+States&f_TPR=r2592000"
TOTAL_PAGES = 40


def run_bb(cmd):
    """执行bb-browser命令"""
    result = subprocess.run(
        cmd, shell=True, capture_output=True, encoding="utf-8", errors="ignore", timeout=60
    )
    return result.stdout.strip()


def extract_page_json():
    """提取当前页面的职位JSON"""
    # 滚动
    run_bb('bb-browser eval "window.scrollTo(0, document.body.scrollHeight)"')
    time.sleep(1)

    # 获取原始输出
    raw = run_bb(
        "bb-browser eval \"JSON.stringify(Array.from(document.querySelectorAll('[data-job-id]')).map(e=>{const l=e.innerText.split('\\n').map(s=>s.trim()).filter(s=>s);return{id:e.dataset.jobId,title:l[0]||'',company:l[2]||'',location:l[3]||''}}))\""
    )

    if not raw:
        return []

    # 跳过第一行metadata，解析剩余JSON
    lines = raw.split("\n")
    json_lines = [l for l in lines if not l.strip().startswith("{")]
    json_str = "\n".join(json_lines).strip()

    if not json_str or json_str == "undefined":
        return []

    try:
        return json.loads(json_str)
    except:
        # 尝试整个输出
        try:
            # 查找JSON数组开始
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start >= 0 and end > start:
                return json.loads(raw[start:end])
        except:
            pass
        return []


def go_to_page(page_num):
    """跳转到指定页"""
    start = page_num * 25
    url = f"{BASE_URL}&start={start}"
    run_bb(f'bb-browser open "{url}"')
    time.sleep(2)


def main():
    # 加载已有进度
    all_jobs = []
    existing_ids = set()

    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                all_jobs = json.load(f)
            existing_ids = {j["id"] for j in all_jobs}
            print(f"已加载 {len(all_jobs)} 条记录")
        except:
            pass

    start_page = len(all_jobs) // 25
    print(f"从第 {start_page + 1} 页开始提取...")

    for page in range(start_page, TOTAL_PAGES):
        print(f"\n=== 第 {page + 1}/{TOTAL_PAGES} 页 ===", flush=True)

        go_to_page(page)
        jobs = extract_page_json()

        new_count = 0
        for j in jobs:
            if j.get("id") and j["id"] not in existing_ids:
                j["url"] = f"https://www.linkedin.com/jobs/view/{j['id']}"
                all_jobs.append(j)
                existing_ids.add(j["id"])
                new_count += 1

        # 保存进度
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(all_jobs, f, ensure_ascii=False)

        print(f"本页 {len(jobs)} 个，新增 {new_count} 个，累计 {len(all_jobs)} 个")

        if len(jobs) == 0:
            print("没有更多职位")
            break

        time.sleep(0.5)

    # 保存最终结果
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "extracted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "total": len(all_jobs),
                "jobs": all_jobs,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    print(f"\n完成! 共 {len(all_jobs)} 个职位")
    print(f"保存至: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
