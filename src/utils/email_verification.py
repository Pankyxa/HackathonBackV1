from datetime import datetime, timedelta
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status
from src.models.user import EmailVerificationToken, User
from src.utils.email_utils import email_sender
from src.settings import settings

VERIFICATION_TOKEN_EXPIRE_HOURS = 24

async def create_verification_token(user_id: uuid.UUID, session: AsyncSession) -> EmailVerificationToken:
    """Создает токен подтверждения email"""
    token = EmailVerificationToken(
        user_id=user_id,
        token=str(uuid.uuid4()),
        expires_at=datetime.utcnow() + timedelta(hours=VERIFICATION_TOKEN_EXPIRE_HOURS)
    )
    session.add(token)
    await session.flush()
    return token

async def send_verification_email(user_email: str, user_name: str, token: str):
    """Отправляет email со ссылкой для подтверждения"""
    verification_url = f"{settings.base_url}/auth/verify-email/{token}"
    
    html_content = f"""
    <html>
        <body>
            <h2>Здравствуйте, {user_name}!</h2>
            <p>Для подтверждения вашего email адреса, пожалуйста, перейдите по следующей ссылке:</p>
            <p><a href="{verification_url}">{verification_url}</a></p>
            <p>Ссылка действительна в течение {VERIFICATION_TOKEN_EXPIRE_HOURS} часов.</p>
            <p>Если вы не регистрировались на нашем сайте, просто проигнорируйте это письмо.</p>
        </body>
    </html>
    """
    
    return email_sender.send_email(
        to_email=user_email,
        subject="Подтверждение email адреса",
        body=html_content,
        is_html=True
    )

async def verify_email_token(token: str, session: AsyncSession) -> User:
    """Проверяет токен и подтверждает email пользователя"""
    query = (
        select(EmailVerificationToken)
        .where(
            EmailVerificationToken.token == token,
            EmailVerificationToken.used == False
        )
    )
    result = await session.execute(query)
    verification_token = result.scalar_one_or_none()

    if not verification_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Недействительный токен подтверждения"
        )

    if verification_token.is_expired:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Срок действия токена истек"
        )

    user_query = select(User).where(User.id == verification_token.user_id)
    result = await session.execute(user_query)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )

    user.email_verified = True
    verification_token.used = True
    
    await session.flush()
    return user