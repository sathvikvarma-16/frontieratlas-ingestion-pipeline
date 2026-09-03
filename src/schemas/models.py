"""Pydantic contracts for raw and extracted pipeline records."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class EntityType(StrEnum):
    STARTUP = "startup"
    PRODUCT = "product"
    PAPER = "research_paper"
    JOB = "job"
    NEWS = "news"


class Source(BaseModel):
    name: str = Field(min_length=1)
    url: HttpUrl


class Envelope(BaseModel):
    schemaVersion: str = "1.0"
    collectedAt: datetime = Field(default_factory=datetime.utcnow)
    source: Source


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_url: HttpUrl
    title: str = Field(min_length=1)
    content: str = ""
    published_at: datetime | None = None
    scraped_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Startup(BaseModel):
    schemaVersion: str = "1.0"
    recordType: Literal["STARTUP"] = "STARTUP"
    source: Source
    collectedAt: datetime = Field(default_factory=datetime.utcnow)
    name: str = Field(min_length=1)
    description: str | None = None
    website: HttpUrl | None = None
    headquarters: str | None = None
    employee_count: int | None = Field(default=None, ge=0)


class Product(BaseModel):
    schemaVersion: str = "1.0"
    recordType: Literal["PRODUCT"] = "PRODUCT"
    source: Source
    collectedAt: datetime = Field(default_factory=datetime.utcnow)
    name: str = Field(min_length=1)
    company: str | None = None
    description: str | None = None
    website: HttpUrl | None = None
    pricing_model: Literal["FREE", "FREEMIUM", "PAID", "ENTERPRISE"] | None = None


class ResearchPaper(BaseModel):
    schemaVersion: str = "1.0"
    recordType: Literal["RESEARCH_PAPER"] = "RESEARCH_PAPER"
    collectedAt: datetime = Field(default_factory=datetime.utcnow)
    title: str = Field(min_length=1)
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    published_at: datetime | None = None
    paper_url: HttpUrl
    github_url: HttpUrl | None = None
    github_stars: int | None = Field(default=None, ge=0)


class Job(BaseModel):
    schemaVersion: str = "1.0"
    recordType: Literal["JOB"] = "JOB"
    collectedAt: datetime = Field(default_factory=datetime.utcnow)
    title: str = Field(min_length=1)
    company: str | None = None
    location: str | None = None
    posted_at: datetime | None = None
    application_url: HttpUrl
    source_url: HttpUrl
    is_remote: bool | None = None
    role_family: str | None = None


class NewsArticle(BaseModel):
    schemaVersion: str = "1.0"
    recordType: Literal["NEWS"] = "NEWS"
    collectedAt: datetime = Field(default_factory=datetime.utcnow)
    title: str = Field(min_length=1)
    summary: str | None = None
    published_at: datetime | None = None
    article_url: HttpUrl
    source_url: HttpUrl
