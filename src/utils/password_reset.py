from datetime import datetime, timedelta, timezone
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status
from src.models.user import PasswordResetToken, User
from src.utils.email_utils import email_sender
from src.settings import settings

PASSWORD_RESET_TOKEN_EXPIRE_HOURS = 1  # Токен действителен 1 час


async def create_password_reset_token(user_id: uuid.UUID, session: AsyncSession) -> PasswordResetToken:
    """Создает токен для сброса пароля"""
    # Деактивируем все предыдущие токены для этого пользователя
    existing_tokens_query = (
        select(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.used == False
        )
    )
    result = await session.execute(existing_tokens_query)
    existing_tokens = result.scalars().all()
    for token in existing_tokens:
        token.used = True

    # Создаем новый токен
    now = datetime.now(timezone.utc)
    token = PasswordResetToken(
        user_id=user_id,
        token=str(uuid.uuid4()),
        created_at=now,  # Явно устанавливаем created_at
        expires_at=now + timedelta(hours=PASSWORD_RESET_TOKEN_EXPIRE_HOURS)
    )
    session.add(token)
    await session.flush()
    return token


async def send_password_reset_email(user_email: str, user_name: str, token: str):
    """Отправляет email со ссылкой для сброса пароля"""
    reset_url = f"{settings.base_url}/auth/reset-password/{token}"

    html_content = f"""
    <!DOCTYPE html>
    <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="margin: 0; padding: 0; background-color: #f5f5f5;">
            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="font-family: Arial, sans-serif;">
                <tr>
                    <td align="center" style="padding: 20px 0;">
                        <table border="0" cellpadding="0" cellspacing="0" width="600" style="background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);">
                            <tr>
                                <td align="center" style="padding: 40px 30px;">
                                    <!-- Header -->
                                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-bottom: 30px;">
                                        <tr>
                                            <td align="center">
                                                <h1 style="color: #2196F3; font-size: 24px; margin: 0;">Восстановление пароля</h1>
                                            </td>
                                        </tr>
                                    </table>

                                    <!-- Content -->
                                    <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                        <tr>
                                            <td align="center" style="padding: 0 0 20px 0;">
                                                <p style="margin: 0; font-size: 16px;">Здравствуйте, {user_name}!</p>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding: 0 0 20px 0;">
                                                <p style="margin: 0;">Вы запросили восстановление пароля для вашего аккаунта.</p>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding: 0 0 20px 0;">
                                                <p style="margin: 0;">Для создания нового пароля нажмите на кнопку ниже:</p>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding: 20px 0;">
                                                <table border="0" cellpadding="0" cellspacing="0">
                                                    <tr>
                                                        <td align="center" bgcolor="#2196F3" style="border-radius: 4px;">
                                                            <a href="{reset_url}" 
                                                               style="display: inline-block; padding: 12px 24px; color: #ffffff; text-decoration: none; font-weight: bold;">
                                                                Восстановить пароль
                                                            </a>
                                                        </td>
                                                    </tr>
                                                </table>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding: 10px 0 20px 0;">
                                                <p style="margin: 0; font-size: 14px; color: #666666;">Или перейдите по ссылке:</p>
                                                <p style="margin: 5px 0 0 0;"><a href="{reset_url}" style="color: #2196F3; word-break: break-all;">{reset_url}</a></p>
                                            </td>
                                        </tr>
                                    </table>

                                    <!-- Warning -->
                                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 20px;">
                                        <tr>
                                            <td align="center" style="padding: 15px; background-color: #fff3cd; border-radius: 4px;">
                                                <p style="margin: 0; font-size: 14px; color: #856404;">
                                                    <strong>Важно:</strong> Если вы не запрашивали восстановление пароля, просто проигнорируйте это письмо. Ваш пароль останется без изменений.
                                                </p>
                                            </td>
                                        </tr>
                                    </table>

                                    <!-- Footer -->
                                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 30px;">
                                        <tr>
                                            <td align="center" style="color: #666666; font-size: 14px;">
                                                <p style="margin: 0;">Ссылка действительна в течение {PASSWORD_RESET_TOKEN_EXPIRE_HOURS} часа.</p>
                                                <p style="margin: 5px 0 0 0;">По соображениям безопасности не передавайте эту ссылку третьим лицам.</p>
                                            </td>
                                        </tr>
                                    </table>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </body>
    </html>
    """

    return email_sender.send_email(
        to_email=user_email,
        subject="Восстановление пароля",
        body=html_content,
        is_html=True
    )


async def verify_password_reset_token(token: str, session: AsyncSession) -> User:
    """Проверяет токен сброса пароля и возвращает пользователя"""
    query = (
        select(PasswordResetToken)
        .where(
            PasswordResetToken.token == token,
            PasswordResetToken.used == False
        )
    )
    result = await session.execute(query)
    reset_token = result.scalar_one_or_none()

    if not reset_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Недействительный токен восстановления пароля"
        )

    if reset_token.is_expired:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Срок действия токена истек. Запросите новую ссылку для восстановления пароля."
        )

    user_query = select(User).where(User.id == reset_token.user_id)
    result = await session.execute(user_query)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )

    return user
