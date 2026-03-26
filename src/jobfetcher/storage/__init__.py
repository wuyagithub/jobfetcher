"""Storage layer for JobFetcher - SQLite and JSON backends."""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from jobfetcher.models import (
    EmploymentType,
    JobListing,
    JobSource,
    Location,
    LocationType,
    Salary,
    SalaryInterval,
)


class JSONStorage:
    """Storage backend using JSON files."""

    def __init__(self, output_dir: str = "./data"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        jobs: list[JobListing],
        filename: Optional[str] = None,
        include_metadata: bool = True,
    ) -> Path:
        """Save jobs to JSON file.

        Args:
            jobs: List of job listings
            filename: Output filename (auto-generated if None)
            include_metadata: Include metadata like scraped_at

        Returns:
            Path to saved file
        """
        if filename is None:
            filename = f"jobs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        filepath = self.output_dir / filename

        data = [job.to_dict() for job in jobs]

        if include_metadata:
            data = {
                "metadata": {
                    "scraped_at": datetime.now().isoformat(),
                    "count": len(jobs),
                    "sources": list(set(job.source.value for job in jobs)),
                },
                "jobs": data,
            }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

        return filepath

    def load(self, filepath: str) -> list[JobListing]:
        """Load jobs from JSON file.

        Args:
            filepath: Path to JSON file

        Returns:
            List of job listings
        """
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict) and "jobs" in data:
            data = data["jobs"]

        return [self._dict_to_job(d) for d in data]

    def _dict_to_job(self, data: dict) -> JobListing:
        """Convert dictionary to JobListing."""
        return JobListing(
            id=data["id"],
            source=JobSource(data["source"]),
            source_url=data["source_url"],
            job_title=data["job_title"],
            company=data.get("company", {}),
            location=data.get("location", {}),
            employment_type=(
                EmploymentType(data["employment_type"]) if data.get("employment_type") else None
            ),
            salary=data.get("salary"),
            description=data.get("description", {}),
            requirements=data.get("requirements", {}),
            posted_date=datetime.fromisoformat(data["posted_date"])
            if data.get("posted_date")
            else None,
            expiry_date=datetime.fromisoformat(data["expiry_date"])
            if data.get("expiry_date")
            else None,
            scraped_at=datetime.fromisoformat(data["scraped_at"])
            if data.get("scraped_at")
            else datetime.now(),
        )


class SQLiteStorage:
    """Storage backend using SQLite database."""

    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        source_url TEXT UNIQUE NOT NULL,
        job_title TEXT NOT NULL,
        company_name TEXT NOT NULL,
        company_url TEXT,
        location_type TEXT,
        city TEXT,
        state TEXT,
        country TEXT DEFAULT 'US',
        postal_code TEXT,
        employment_type TEXT,
        salary_currency TEXT,
        salary_min REAL,
        salary_max REAL,
        salary_interval TEXT,
        description_text TEXT,
        description_html TEXT,
        requirements_json TEXT,
        posted_date TEXT,
        expiry_date TEXT,
        scraped_at TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """

    CREATE_INDEXES_SQL = [
        "CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_title ON jobs(job_title)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_location ON jobs(city, state, country)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_posted_date ON jobs(posted_date)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_name)",
    ]

    INSERT_SQL = """
    INSERT OR REPLACE INTO jobs (
        id, source, source_url, job_title,
        company_name, company_url,
        location_type, city, state, country, postal_code,
        employment_type,
        salary_currency, salary_min, salary_max, salary_interval,
        description_text, description_html,
        requirements_json,
        posted_date, expiry_date,
        scraped_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    def __init__(self, db_path: str = "./data/jobs.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(self.CREATE_TABLE_SQL)
            for sql in self.CREATE_INDEXES_SQL:
                conn.execute(sql)
            conn.commit()

    def save(self, jobs: list[JobListing]) -> int:
        """Save jobs to database.

        Args:
            jobs: List of job listings

        Returns:
            Number of jobs saved
        """
        with sqlite3.connect(self.db_path) as conn:
            for job in jobs:
                conn.execute(self.INSERT_SQL, self._job_to_tuple(job))
            conn.commit()
        return len(jobs)

    def _job_to_tuple(self, job: JobListing) -> tuple:
        """Convert JobListing to database tuple."""
        return (
            job.id,
            job.source.value,
            job.source_url,
            job.job_title,
            job.company.name,
            job.company.url,
            job.location.type.value if job.location.type else None,
            job.location.city,
            job.location.state,
            job.location.country,
            job.location.postal_code,
            job.employment_type.value if job.employment_type else None,
            job.salary.currency if job.salary else None,
            job.salary.min if job.salary else None,
            job.salary.max if job.salary else None,
            job.salary.interval.value if job.salary and job.salary.interval else None,
            job.description.raw,
            job.description.html,
            json.dumps(job.requirements.model_dump()) if job.requirements else None,
            job.posted_date.isoformat() if job.posted_date else None,
            job.expiry_date.isoformat() if job.expiry_date else None,
            job.scraped_at.isoformat(),
        )

    def query(
        self,
        keyword: Optional[str] = None,
        source: Optional[JobSource] = None,
        location: Optional[str] = None,
        employment_type: Optional[EmploymentType] = None,
        salary_min: Optional[float] = None,
        salary_max: Optional[float] = None,
        limit: int = 100,
    ) -> list[JobListing]:
        """Query jobs with filters.

        Args:
            keyword: Filter by keyword in title or company
            source: Filter by source
            location: Filter by location
            employment_type: Filter by employment type
            salary_min: Filter by minimum salary
            salary_max: Filter by maximum salary
            limit: Maximum results

        Returns:
            List of matching job listings
        """
        conditions = []
        params = []

        if keyword:
            conditions.append("(job_title LIKE ? OR company_name LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])

        if source:
            conditions.append("source = ?")
            params.append(source.value)

        if location:
            conditions.append("(city LIKE ? OR state LIKE ? OR country LIKE ?)")
            params.extend([f"%{location}%", f"%{location}%", f"%{location}%"])

        if employment_type:
            conditions.append("employment_type = ?")
            params.append(employment_type.value)

        if salary_min:
            conditions.append("salary_min >= ?")
            params.append(salary_min)

        if salary_max:
            conditions.append("salary_max <= ?")
            params.append(salary_max)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        sql = f"""
            SELECT * FROM jobs
            WHERE {where_clause}
            ORDER BY posted_date DESC, scraped_at DESC
            LIMIT ?
        """
        params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(sql, params)
            return [self._row_to_job(row) for row in cursor.fetchall()]

    def _row_to_job(self, row: sqlite3.Row) -> JobListing:
        """Convert database row to JobListing."""
        return JobListing(
            id=row["id"],
            source=JobSource(row["source"]),
            source_url=row["source_url"],
            job_title=row["job_title"],
            company={
                "name": row["company_name"],
                "url": row["company_url"],
            },
            location={
                "type": LocationType(row["location_type"]) if row["location_type"] else None,
                "city": row["city"],
                "state": row["state"],
                "country": row["country"],
                "postal_code": row["postal_code"],
            },
            employment_type=(
                EmploymentType(row["employment_type"]) if row["employment_type"] else None
            ),
            salary={
                "currency": row["salary_currency"],
                "min": row["salary_min"],
                "max": row["salary_max"],
                "interval": SalaryInterval(row["salary_interval"])
                if row["salary_interval"]
                else None,
            }
            if row["salary_currency"]
            else None,
            description={
                "raw": row["description_text"],
                "html": row["description_html"],
            },
            requirements=(json.loads(row["requirements_json"]) if row["requirements_json"] else {}),
            posted_date=datetime.fromisoformat(row["posted_date"]) if row["posted_date"] else None,
            expiry_date=datetime.fromisoformat(row["expiry_date"]) if row["expiry_date"] else None,
            scraped_at=datetime.fromisoformat(row["scraped_at"]),
        )

    def get_stats(self) -> dict:
        """Get database statistics.

        Returns:
            Dictionary with stats
        """
        with sqlite3.connect(self.db_path) as conn:
            # Total count
            total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

            # Count by source
            source_counts = dict(
                conn.execute("SELECT source, COUNT(*) FROM jobs GROUP BY source").fetchall()
            )

            # Recent count
            today = datetime.now().date()
            recent = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE date(scraped_at) = ?",
                (today.isoformat(),),
            ).fetchone()[0]

            return {
                "total_jobs": total,
                "by_source": source_counts,
                "scraped_today": recent,
            }

    def delete_old(self, days: int = 30) -> int:
        """Delete jobs older than specified days.

        Args:
            days: Number of days to keep

        Returns:
            Number of jobs deleted
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM jobs WHERE date(scraped_at) < date('now', ?)",
                (f"-{days} days",),
            )
            conn.commit()
            return cursor.rowcount


class CSVStorage:
    """Export jobs to CSV format."""

    def __init__(self, output_dir: str = "./data"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save(self, jobs: list[JobListing], filename: Optional[str] = None) -> Path:
        """Save jobs to CSV file.

        Args:
            jobs: List of job listings
            filename: Output filename (auto-generated if None)

        Returns:
            Path to saved file
        """
        if filename is None:
            filename = f"jobs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        filepath = self.output_dir / filename

        fieldnames = [
            "id",
            "source",
            "source_url",
            "job_title",
            "company_name",
            "company_url",
            "location_type",
            "city",
            "state",
            "country",
            "postal_code",
            "employment_type",
            "salary_currency",
            "salary_min",
            "salary_max",
            "salary_interval",
            "description_text",
            "posted_date",
            "expiry_date",
            "scraped_at",
        ]

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for job in jobs:
                writer.writerow(
                    {
                        "id": job.id,
                        "source": job.source.value,
                        "source_url": job.source_url,
                        "job_title": job.job_title,
                        "company_name": job.company.name,
                        "company_url": job.company.url,
                        "location_type": job.location.type.value if job.location.type else "",
                        "city": job.location.city or "",
                        "state": job.location.state or "",
                        "country": job.location.country,
                        "postal_code": job.location.postal_code or "",
                        "employment_type": job.employment_type.value if job.employment_type else "",
                        "salary_currency": job.salary.currency if job.salary else "",
                        "salary_min": job.salary.min if job.salary else "",
                        "salary_max": job.salary.max if job.salary else "",
                        "salary_interval": job.salary.interval.value
                        if job.salary and job.salary.interval
                        else "",
                        "description_text": job.description.raw[:5000],  # Limit length
                        "posted_date": job.posted_date.isoformat() if job.posted_date else "",
                        "expiry_date": job.expiry_date.isoformat() if job.expiry_date else "",
                        "scraped_at": job.scraped_at.isoformat(),
                    }
                )

        return filepath
