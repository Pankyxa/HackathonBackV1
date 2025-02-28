from typing import List
import asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.models import Team, TeamMember, User
from src.utils.email_utils import email_sender
from src.settings import settings
from src.utils.router_states import team_router_state


async def send_team_confirmation_email(team: Team, members: List[User]):
    """Отправляет email с подтверждением участия в хакатоне"""
    members_list = ", ".join([member.full_name for member in members])

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
                                                <h1 style="color: #2196F3; font-size: 24px; margin: 0;">Подтверждение участия в хакатоне</h1>
                                            </td>
                                        </tr>
                                    </table>

                                    <!-- Content -->
                                    <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                        <tr>
                                            <td align="center" style="padding: 0 0 20px 0;">
                                                <p style="margin: 0;">Поздравляем! Ваша команда "{team.team_name}" успешно зарегистрирована для участия в хакатоне.</p>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding: 20px 0; background-color: #f5f5f5; border-radius: 4px;">
                                                <h3 style="margin: 0 0 10px 0;">Состав команды:</h3>
                                                <p style="margin: 0;">{members_list}</p>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding: 20px 0;">
                                                <p style="margin: 0 0 10px 0;">Следите за обновлениями на нашем сайте:</p>
                                                <a href="{settings.base_url}" style="color: #2196F3; text-decoration: none;">Хакатон "Цифровые двойники в энергетике"</a>
                                            </td>
                                        </tr>
                                    </table>

                                    <!-- Footer -->
                                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 30px;">
                                        <tr>
                                            <td align="center" style="color: #666666; font-size: 14px;">
                                                <p style="margin: 0;">Желаем удачи в соревновании!</p>
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

    for member in members:
        email_sender.send_email(
            to_email=member.email,
            subject="Подтверждение участия в хакатоне",
            body=html_content,
            is_html=True
        )
        await asyncio.sleep(10)


async def notify_active_teams(session: AsyncSession):
    """Отправляет уведомления всем активным командам"""
    teams_query = (
        select(Team)
        .join(TeamMember)
        .join(User)
        .where(Team.status == "active")
    )

    result = await session.execute(teams_query)
    teams = result.scalars().unique().all()

    for team in teams:
        members_query = (
            select(User)
            .join(TeamMember)
            .where(
                TeamMember.team_id == team.id,
                TeamMember.status_id == team_router_state.accepted_status_id
            )
        )
        members_result = await session.execute(members_query)
        members = members_result.scalars().all()

        await send_team_confirmation_email(team, members)


async def send_team_invitation_email(user: User, team: Team):
    """Отправляет email с приглашением в команду"""
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
                                                <h1 style="color: #2196F3; font-size: 24px; margin: 0;">Приглашение в команду</h1>
                                            </td>
                                        </tr>
                                    </table>

                                    <!-- Content -->
                                    <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                        <tr>
                                            <td align="center" style="padding: 0 0 20px 0;">
                                                <p style="margin: 0;">Здравствуйте, {user.full_name}!</p>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding: 0 0 20px 0;">
                                                <p style="margin: 0;">Вас приглашают присоединиться к команде "{team.team_name}".</p>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding: 20px 0;">
                                                <table border="0" cellpadding="0" cellspacing="0">
                                                    <tr>
                                                        <td align="center" bgcolor="#2196F3" style="border-radius: 4px;">
                                                            <a href="{settings.base_url}/profile" 
                                                               style="display: inline-block; padding: 12px 24px; color: #ffffff; text-decoration: none; font-weight: bold;">
                                                                Перейти в личный кабинет
                                                            </a>
                                                        </td>
                                                    </tr>
                                                </table>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding: 0 0 20px 0;">
                                                <p style="margin: 0;">В личном кабинете вы сможете принять или отклонить приглашение.</p>
                                            </td>
                                        </tr>
                                    </table>

                                    <!-- Footer -->
                                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 30px;">
                                        <tr>
                                            <td align="center" style="color: #666666; font-size: 14px;">
                                                <p style="margin: 0;">Если вы не регистрировались на нашем сайте, просто проигнорируйте это письмо.</p>
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

    email_sender.send_email(
        to_email=user.email,
        subject="Приглашение в команду",
        body=html_content,
        is_html=True
    )


async def send_registration_confirmation_email(user: User, confirmation_link: str):
    """Отправляет email с подтверждением регистрации"""
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
                                                <h1 style="color: #2196F3; font-size: 24px; margin: 0;">Подтверждение регистрации</h1>
                                            </td>
                                        </tr>
                                    </table>

                                    <!-- Content -->
                                    <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                        <tr>
                                            <td align="center" style="padding: 0 0 20px 0;">
                                                <p style="margin: 0;">Здравствуйте, {user.full_name}!</p>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding: 0 0 20px 0;">
                                                <p style="margin: 0;">Для завершения регистрации перейдите по ссылке:</p>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding: 20px 0;">
                                                <table border="0" cellpadding="0" cellspacing="0">
                                                    <tr>
                                                        <td align="center" bgcolor="#2196F3" style="border-radius: 4px;">
                                                            <a href="{confirmation_link}" 
                                                               style="display: inline-block; padding: 12px 24px; color: #ffffff; text-decoration: none; font-weight: bold;">
                                                                Подтвердить email
                                                            </a>
                                                        </td>
                                                    </tr>
                                                </table>
                                            </td>
                                        </tr>
                                    </table>

                                    <!-- Footer -->
                                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 30px;">
                                        <tr>
                                            <td align="center" style="color: #666666; font-size: 14px;">
                                                <p style="margin: 0;">Если вы не регистрировались на нашем сайте, просто проигнорируйте это письмо.</p>
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

    email_sender.send_email(
        to_email=user.email,
        subject="Подтверждение регистрации",
        body=html_content,
        is_html=True
    )