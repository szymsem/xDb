from fastapi import APIRouter, Depends
from models.user import User
from services.auth import get_current_user
from services.notification_service import send_email_notification

router = APIRouter()

@router.post("/notifications/test")
async def send_test_email(
    subject: str,
    message: str,
    current_user: User = Depends(get_current_user)
):
    await send_email_notification(
        user=current_user,
        subject=subject,
        template_name="basic.html",
        context={"message": message}
    )
    return {"status": "test email sent"}