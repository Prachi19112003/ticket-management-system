import base64
import httpx
from email.mime.text import MIMEText
from app.core.config import settings
from app.core.exceptions import GmailException
from app.core.logging import logger

class GmailClient:
    def __init__(self) -> None:
        self.token_url = "https://oauth2.googleapis.com/token"
        self.send_url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

    async def _get_access_token(self) -> str:
        """Exchanges GMAIL_REFRESH_TOKEN for a temporary GMail OAuth2 access token."""
        payload = {
            "client_id": settings.GMAIL_CLIENT_ID,
            "client_secret": settings.GMAIL_CLIENT_SECRET,
            "refresh_token": settings.GMAIL_REFRESH_TOKEN,
            "grant_type": "refresh_token"
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.token_url, data=payload)
                if response.status_code != 200:
                    raise GmailException(
                        f"OAuth2 refresh token exchange failed with status {response.status_code}",
                        details={"response_body": response.text}
                    )
                data = response.json()
                access_token = data.get("access_token")
                if not access_token:
                    raise GmailException("OAuth2 refresh token response did not contain access_token")
                return access_token
        except GmailException:
            raise
        except httpx.HTTPError as e:
            logger.error("Network error during Gmail OAuth2 token exchange", error=str(e))
            raise GmailException(
                "Network timeout or error communicating with Google OAuth server.",
                details={"original_error": str(e)}
            )
        except Exception as e:
            logger.error("Unexpected error during Gmail OAuth2 token exchange", error=str(e))
            raise GmailException(
                "Unexpected error during Gmail OAuth2 token exchange.",
                details={"original_error": str(e)}
            )

    async def send_email(self, to_email: str, subject: str, body: str, cc_list: list[str] = None) -> str:
        """
        Sends an email using the Gmail REST API.
        Returns:
            str: The Gmail message ID on success.
        Raises:
            GmailException: On network failures or unauthorized requests.
        """
        logger.info("Preparing to send email via Gmail API", to=to_email, subject=subject, cc=cc_list)
        
        try:
            # 1. Get Access Token
            access_token = await self._get_access_token()

            # 2. Build MIME Message
            mime_msg = MIMEText(body)
            mime_msg["From"] = "me"
            mime_msg["To"] = to_email
            mime_msg["Subject"] = subject
            
            if cc_list:
                mime_msg["Cc"] = ", ".join(cc_list)

            # 3. Base64url encode the message
            raw_bytes = mime_msg.as_bytes()
            encoded = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")

            # 4. Submit to GMail Send API
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            payload = {"raw": encoded}

            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(self.send_url, headers=headers, json=payload)
                if response.status_code != 200:
                    logger.error("Gmail API message send failed", status=response.status_code, body=response.text)
                    raise GmailException(
                        f"Gmail API send failed with status {response.status_code}",
                        details={"response_body": response.text}
                    )
                
                result = response.json()
                gmail_id = result.get("id")
                logger.info("Email sent successfully via Gmail API", gmail_id=gmail_id)
                return gmail_id
                
        except GmailException:
            raise
        except httpx.HTTPError as e:
            logger.error("Network error during Gmail API send", error=str(e))
            raise GmailException(
                "Failed to send email due to communication timeout with Gmail API.",
                details={"original_error": str(e)}
            )
        except Exception as e:
            logger.error("Unexpected error in Gmail client send_email", error=str(e))
            raise GmailException(
                "An unexpected error occurred while preparing or sending email via Gmail.",
                details={"original_error": str(e)}
            )
