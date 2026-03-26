"""Command-line interface for JobFetcher."""

from __future__ import annotations

import asyncio
import sys
from typing import Optional

import click
from dotenv import load_dotenv

from jobfetcher.models import (
    EmploymentType,
    JobSource,
    LocationType,
    ScraperConfig,
)
from jobfetcher.scrapers import (
    LinkedInScraper,
)
from jobfetcher.storage import (
    CSVStorage,
    JSONStorage,
    SQLiteStorage,
)

load_dotenv()


def create_scraper(source: str, config: ScraperConfig):
    """Create a scraper instance."""
    scrapers = {
        "linkedin": LinkedInScraper,
    }

    if source not in scrapers:
        raise ValueError(f"Unknown source: {source}. Available: {', '.join(scrapers.keys())}")

    return scrapers[source](config)


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """JobFetcher - Job search aggregation agent."""
    pass


@cli.command()
@click.argument("keywords")
@click.argument("location", default="")
@click.option(
    "--source",
    "-s",
    multiple=True,
    default=["linkedin"],
    help="Job sources to search (can specify multiple)",
)
@click.option(
    "--limit",
    "-l",
    default=100,
    help="Maximum number of results per source",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    help="Output file path",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(["json", "csv", "sqlite"]),
    default="json",
    help="Output format",
)
@click.option(
    "--requests-per-second",
    default=1.0,
    help="Rate limit: requests per second",
)
@click.option(
    "--max-retries",
    default=3,
    help="Maximum number of retries",
)
@click.option(
    "--timeout",
    default=30.0,
    help="Request timeout in seconds",
)
def search(
    keywords: str,
    location: str,
    source: tuple,
    limit: int,
    output: Optional[str],
    format: str,
    requests_per_second: float,
    max_retries: int,
    timeout: float,
):
    """Search for jobs on specified platforms.

    Example:
        jobfetcher search "python developer" "San Francisco" -s linkedin
    """
    config = ScraperConfig(
        requests_per_second=requests_per_second,
        max_retries=max_retries,
        timeout=timeout,
    )

    async def run():
        all_jobs = []

        for src in source:
            click.echo(f"Searching {src}...")
            scraper = create_scraper(src, config)

            try:
                async with scraper:
                    jobs = await scraper.search(
                        keywords=keywords,
                        location=location,
                        limit=limit,
                    )
                    all_jobs.extend(jobs)
                    click.echo(f"  Found {len(jobs)} jobs from {src}")
            except Exception as e:
                click.echo(f"  Error: {e}", err=True)

        click.echo(f"\nTotal: {len(all_jobs)} jobs")

        # Save results
        if format in ("json", "csv"):
            storage = JSONStorage() if format == "json" else CSVStorage()
            filepath = storage.save(all_jobs, output)
            click.echo(f"Saved to: {filepath}")
        else:
            sqlite_storage = SQLiteStorage()
            count = sqlite_storage.save(all_jobs)
            click.echo(f"Saved {count} jobs to database")

    asyncio.run(run())


@cli.command()
@click.option(
    "--keyword",
    "-k",
    help="Filter by keyword",
)
@click.option(
    "--source",
    "-s",
    type=click.Choice(["linkedin"]),
    help="Filter by source",
)
@click.option(
    "--location",
    "-l",
    help="Filter by location",
)
@click.option(
    "--limit",
    "-l",
    default=50,
    help="Maximum number of results",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    help="Output file path",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(["json", "csv"]),
    default="json",
    help="Output format",
)
def query(
    keyword: Optional[str],
    source: Optional[str],
    location: Optional[str],
    limit: int,
    output: Optional[str],
    format: str,
):
    """Query previously scraped jobs."""
    storage = SQLiteStorage()

    jobs = storage.query(
        keyword=keyword,
        source=JobSource(source) if source else None,
        location=location,
        limit=limit,
    )

    click.echo(f"Found {len(jobs)} jobs")

    if format == "json":
        json_storage = JSONStorage()
        filepath = json_storage.save(jobs, output)
    else:
        csv_storage = CSVStorage()
        filepath = csv_storage.save(jobs, output)

    click.echo(f"Saved to: {filepath}")


@cli.command()
def stats():
    """Show database statistics."""
    storage = SQLiteStorage()
    stats = storage.get_stats()

    click.echo("Job Database Statistics")
    click.echo("=" * 30)
    click.echo(f"Total jobs: {stats['total_jobs']}")
    click.echo(f"Scraped today: {stats['scraped_today']}")
    click.echo("\nBy source:")
    for source, count in stats["by_source"].items():
        click.echo(f"  {source}: {count}")


@cli.command()
@click.option(
    "--days",
    "-d",
    default=30,
    help="Delete jobs older than this many days",
)
def cleanup(days: int):
    """Clean up old job listings."""
    storage = SQLiteStorage()
    deleted = storage.delete_old(days)
    click.echo(f"Deleted {deleted} old job listings")


@cli.command()
@click.argument("keywords")
@click.argument("location", default="")
@click.option(
    "--source",
    "-s",
    multiple=True,
    default=["linkedin"],
    help="Job sources to search",
)
@click.option(
    "--limit",
    "-l",
    default=100,
    help="Maximum number of results per source",
)
@click.option(
    "--interval",
    "-i",
    default="hourly",
    type=click.Choice(["hourly", "daily", "weekly"]),
    help="Schedule interval",
)
def schedule(
    keywords: str,
    location: str,
    source: tuple,
    limit: int,
    interval: str,
):
    """Schedule recurring job searches.

    Note: This is a placeholder. For production, use cron or a task scheduler.
    """
    click.echo(f"Scheduled search: {keywords} in {location}")
    click.echo(f"Sources: {', '.join(source)}")
    click.echo(f"Interval: {interval}")
    click.echo("\nFor production use, set up a cron job or use a task scheduler.")
    click.echo("Example cron (daily at 6am):")
    click.echo(
        '  0 6 * * * jobfetcher search "keywords" "location" -s linkedin --output /path/to/output.json'
    )


def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
