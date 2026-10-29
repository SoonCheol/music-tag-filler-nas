"""API request models shared by the application endpoints."""
from typing import List, Dict, Optional, Literal

from pydantic import BaseModel, Field, ConfigDict


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sub_path: str = ""
    paths: List[str] = Field(default_factory=list, max_length=200)
    recurse: bool = True
    only_empty: bool = True
    fill_lyrics: bool = False
    rename: bool = False
    use_fingerprint: bool = False
    search_mode: Literal["integrated", "itunes", "musicbrainz", "quick"] = "integrated"
    force: bool = False
    country: Optional[Literal["KR", "US", "JP", "CN", "TW", "HK", "GB", "DE", "FR"]] = None


class DeleteJobsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: List[str] = Field(min_length=1,max_length=1000)


TagField = Literal["title", "artist", "album", "albumartist", "track", "year", "genre"]


class SaveItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection: Literal["auto", "manual", "edit", "none"]
    candidate_id: Optional[str] = None
    values: Dict[TagField, str] = Field(default_factory=dict)
    fields: List[TagField] = Field(default_factory=list)
    include_cover: bool = False
    cover_id: Optional[str] = None
    include_ids: bool = False
    lyrics_id: Optional[str] = None
    approve_manual_lyrics_mismatch: bool = False
    lyrics_text: Optional[str] = Field(default=None, max_length=30000)


class SaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["current", "selected", "all"]
    paths: List[str]
    checked_paths: List[str] = Field(default_factory=list)
    items: List[SaveItem]
    save_cover: bool = True
    save_lyrics: bool = True
    only_empty: bool = True
    fill_lyrics: bool = False
    save_synced: bool = False
    create_lrc: bool = False
    rename: bool = False
    cover_max_px: Optional[int] = Field(default=None, ge=100, le=1000)
    artist_name_preference: Literal["original", "latin"] = "original"


class LyricsSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    title: str = Field(max_length=4096)
    artist: str = Field(max_length=4096)
    force: bool = False
    candidate_id: Optional[str] = None


class RevertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    query: str = Field(default="", max_length=500)
    mode: Literal["text", "sound"] = "text"
    search_mode: Literal["integrated", "itunes", "musicbrainz", "quick"] = "integrated"
    preserve_candidate_id: Optional[str] = None
    country: Optional[Literal["KR", "US", "JP", "CN", "TW", "HK", "GB", "DE", "FR"]] = None
    use_fingerprint: bool = False
    expected_revision: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class RenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    stem: str = Field(max_length=255)
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class CandidateLyricsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    candidate_id: str
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    force: bool = False
