from pydantic import BaseModel, Field, EmailStr

class GmailWebhookPayload(BaseModel):
    message_id: str = Field(..., description="Unique Gmail Message-ID (used for deduplication).")
    subject: str = Field(..., description="Raw subject line of the email.")
    body: str = Field(..., description="Raw body text or HTML content.")
    from_email: EmailStr = Field(..., description="Sender's email address.")
    from_name: str | None = Field(None, description="Sender's display name.")
    gmail_thread_id: str | None = Field(None, description="Native Gmail thread ID.")
    headers: dict[str, str] = Field(default_factory=dict, description="Email header dictionary (containing References, In-Reply-To, etc.).")
