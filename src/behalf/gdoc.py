"""Publish the one-pager to a shared Google Doc, in place, keeping its URL."""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
]

HEADING_STYLES = {1: "HEADING_1", 2: "HEADING_2", 3: "HEADING_3"}
EMPHASIS = re.compile(r"(\*\*|__|`)")
SUBSCRIPT = re.compile(r"</?sub>")


class GoogleDocError(RuntimeError):
    pass


@dataclass
class Block:
    text: str
    style: str = "NORMAL_TEXT"
    bullet: bool = False


def parse_markdown(page: str) -> list[Block]:
    blocks: list[Block] = []
    for raw in page.splitlines():
        line = SUBSCRIPT.sub("", raw).rstrip()
        if not line.strip():
            continue
        heading = re.match(r"^(#{1,3})\s+(.*)$", line)
        if heading:
            blocks.append(Block(heading.group(2).strip(), HEADING_STYLES[len(heading.group(1))]))
            continue
        if line.lstrip().startswith(("- ", "* ")):
            blocks.append(Block(line.lstrip()[2:].strip(), bullet=True))
            continue
        if line.lstrip().startswith("> "):
            blocks.append(Block(line.lstrip()[2:].strip()))
            continue
        blocks.append(Block(line.strip()))
    return [Block(EMPHASIS.sub("", b.text), b.style, b.bullet) for b in blocks if b.text]


def build_requests(blocks: list[Block], end_index: int) -> list[dict]:
    requests: list[dict] = []
    if end_index > 2:
        requests.append(
            {"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end_index - 1}}}
        )

    text = "".join(f"{b.text}\n" for b in blocks)
    if not text:
        return requests
    requests.append({"insertText": {"location": {"index": 1}, "text": text}})

    cursor = 1
    for block in blocks:
        start, cursor = cursor, cursor + len(block.text) + 1
        requests.append(
            {
                "updateParagraphStyle": {
                    "range": {"startIndex": start, "endIndex": cursor},
                    "paragraphStyle": {"namedStyleType": block.style},
                    "fields": "namedStyleType",
                }
            }
        )
        if block.bullet:
            requests.append(
                {
                    "createParagraphBullets": {
                        "range": {"startIndex": start, "endIndex": cursor},
                        "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                    }
                }
            )
    return requests


@dataclass
class GoogleDocPublisher:
    state_dir: Path
    title: str
    client_id: str
    client_secret: str
    share_with: list[str] = field(default_factory=list)
    document_id: str = ""

    @property
    def token_path(self) -> Path:
        return self.state_dir / "google-token.json"

    @property
    def pointer_path(self) -> Path:
        return self.state_dir / "gdoc.json"

    def url(self) -> str:
        return f"https://docs.google.com/document/d/{self.document_id}/edit"

    def credentials(self):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise GoogleDocError(
                'Google support is not installed. Run: pip install "behalf[google]"'
            ) from exc

        if not self.client_id or not self.client_secret:
            raise GoogleDocError(
                "set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET in .env"
            )

        creds = None
        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif not creds or not creds.valid:
            if not sys.stdin.isatty():
                raise GoogleDocError(
                    "no cached Google token and no terminal to grant consent in. "
                    "Run `behalf publish` once interactively first."
                )
            flow = InstalledAppFlow.from_client_config(
                {
                    "installed": {
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": ["http://localhost"],
                    }
                },
                SCOPES,
            )
            print("Opening your browser for Google consent…", flush=True)
            creds = flow.run_local_server(port=0, prompt="consent")

        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(creds.to_json(), encoding="utf-8")
        self.token_path.chmod(0o600)
        return creds

    def services(self):
        from googleapiclient.discovery import build

        creds = self.credentials()
        return (
            build("docs", "v1", credentials=creds, cache_discovery=False),
            build("drive", "v3", credentials=creds, cache_discovery=False),
        )

    def remember(self) -> None:
        self.pointer_path.write_text(
            json.dumps({"document_id": self.document_id, "title": self.title}, indent=2),
            encoding="utf-8",
        )

    def recall(self) -> str:
        if self.document_id:
            return self.document_id
        if self.pointer_path.exists():
            self.document_id = json.loads(self.pointer_path.read_text()).get("document_id", "")
        return self.document_id

    def share(self, drive, emails: list[str]) -> None:
        for email in sorted({e.strip() for e in emails if e and e.strip()}):
            try:
                drive.permissions().create(
                    fileId=self.document_id,
                    body={"type": "user", "role": "writer", "emailAddress": email},
                    sendNotificationEmail=True,
                    fields="id",
                ).execute()
                print(f"shared with {email}", flush=True)
            except Exception as exc:
                print(f"could not share with {email}: {exc}", flush=True)

    def publish(self, page: str) -> str:
        docs, drive = self.services()
        self.recall()

        if not self.document_id:
            created = docs.documents().create(body={"title": self.title}).execute()
            self.document_id = created["documentId"]
            self.remember()
            print(f"created {self.url()}", flush=True)

        try:
            document = docs.documents().get(documentId=self.document_id).execute()
        except Exception as exc:
            raise GoogleDocError(f"cannot open document {self.document_id}: {exc}") from exc

        content = document.get("body", {}).get("content", [])
        end_index = content[-1].get("endIndex", 1) if content else 1
        requests = build_requests(parse_markdown(page), end_index)
        if requests:
            docs.documents().batchUpdate(
                documentId=self.document_id, body={"requests": requests}
            ).execute()

        if self.share_with:
            self.share(drive, self.share_with)
        return self.url()
