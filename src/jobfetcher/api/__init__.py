"""FastAPI interface for JobFetcher."""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from jobfetcher.models import (
    EmploymentType,
    JobListing,
    JobSource,
    LocationType,
    ScraperConfig,
    SearchFilters,
)
from jobfetcher.scrapers import (
    LinkedInScraper,
)
from jobfetcher.storage import JSONStorage, SQLiteStorage


app = FastAPI(
    title="JobFetcher API",
    description="Job search aggregation API for scraping LinkedIn",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/Response models
class SearchRequest(BaseModel):
    """Request model for job search."""

    keywords: str
    location: str = ""
    sources: list[str] = ["linkedin"]
    limit: int = 100
    config: Optional[ScraperConfig] = None


class JobResponse(BaseModel):
    """Response model for job listing."""

    id: str
    source: str
    source_url: str
    job_title: str
    company_name: str
    company_url: Optional[str]
    location_display: str
    location_type: Optional[str]
    employment_type: Optional[str]
    salary_display: Optional[str]
    posted_date: Optional[str]
    scraped_at: str

    class Config:
        from_attributes = True


class StatsResponse(BaseModel):
    """Response model for statistics."""

    total_jobs: int
    by_source: dict
    scraped_today: int


def job_to_response(job: JobListing) -> JobResponse:
    """Convert JobListing to response model."""
    return JobResponse(
        id=job.id,
        source=job.source.value,
        source_url=job.source_url,
        job_title=job.job_title,
        company_name=job.company.name,
        company_url=job.company.url,
        location_display=job.location.to_display_string(),
        location_type=job.location.type.value if job.location.type else None,
        employment_type=job.employment_type.value if job.employment_type else None,
        salary_display=job.salary.to_display_string() if job.salary else None,
        posted_date=job.posted_date.isoformat() if job.posted_date else None,
        scraped_at=job.scraped_at.isoformat(),
    )


# Initialize storage
json_storage = JSONStorage()
sqlite_storage = SQLiteStorage()


# Endpoints
@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "JobFetcher API",
        "version": "0.1.0",
        "description": "Job search aggregation API",
    }


@app.post("/search", response_model=list[JobResponse])
async def search_jobs(request: SearchRequest):
    """Search for jobs across multiple platforms.

    Args:
        request: Search request with keywords, location, sources

    Returns:
        List of job listings
    """
    config = request.config or ScraperConfig()
    results = []
    errors = []

    # Run scrapers concurrently
    async def run_scraper(scraper_class, source_name: str):
        try:
            scraper = scraper_class(config)
            async with scraper:
                jobs = await scraper.search(
                    keywords=request.keywords,
                    location=request.location,
                    limit=request.limit,
                )
                return jobs
        except Exception as e:
            errors.append(f"{source_name}: {str(e)}")
            return []

    # Create scraper tasks
    tasks = []
    source_map = {
        "linkedin": (LinkedInScraper, "linkedin"),
    }

    for source in request.sources:
        if source in source_map:
            scraper_class, _ = source_map[source]
            tasks.append(run_scraper(scraper_class, source))

    # Run all scrapers concurrently
    all_jobs = await asyncio.gather(*tasks)

    # Flatten results
    for jobs in all_jobs:
        results.extend(jobs)

    # Limit total results
    results = results[: request.limit]

    # Save to storage
    if results:
        try:
            sqlite_storage.save(results)
        except Exception:
            pass  # Ignore storage errors

    return [job_to_response(job) for job in results]


@app.get("/jobs", response_model=list[JobResponse])
async def get_jobs(
    keyword: Optional[str] = Query(None, description="Filter by keyword"),
    source: Optional[str] = Query(None, description="Filter by source"),
    location: Optional[str] = Query(None, description="Filter by location"),
    employment_type: Optional[str] = Query(None, description="Filter by employment type"),
    salary_min: Optional[float] = Query(None, description="Minimum salary"),
    salary_max: Optional[float] = Query(None, description="Maximum salary"),
    limit: int = Query(50, ge=1, le=1000),
):
    """Get previously scraped jobs with optional filters."""
    try:
        jobs = sqlite_storage.query(
            keyword=keyword,
            source=JobSource(source) if source else None,
            location=location,
            employment_type=EmploymentType(employment_type) if employment_type else None,
            salary_min=salary_min,
            salary_max=salary_max,
            limit=limit,
        )
        return [job_to_response(job) for job in jobs]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats", response_model=StatsResponse)
async def get_stats():
    """Get database statistics."""
    try:
        stats = sqlite_storage.get_stats()
        return StatsResponse(**stats)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/export")
async def export_jobs(
    format: str = Query("json", regex="^(json|csv)$"),
    keyword: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
):
    """Export jobs to file.

    Args:
        format: Export format (json or csv)
        keyword: Filter by keyword
        source: Filter by source

    Returns:
        Download URL or file path
    """
    try:
        jobs = sqlite_storage.query(
            keyword=keyword,
            source=JobSource(source) if source else None,
            limit=10000,
        )

        if format == "json":
            filepath = json_storage.save(jobs)
        else:
            from jobfetcher.storage import CSVStorage

            csv_storage = CSVStorage()
            filepath = csv_storage.save(jobs)

        return {"file": str(filepath), "count": len(jobs)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/cleanup")
async def cleanup_old_jobs(days: int = Query(30, ge=1, le=365)):
    """Clean up old job listings.

    Args:
        days: Delete jobs older than this many days

    Returns:
        Number of jobs deleted
    """
    try:
        deleted = sqlite_storage.delete_old(days)
        return {"deleted": deleted}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
