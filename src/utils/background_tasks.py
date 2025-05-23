import logging
from datetime import datetime, timedelta
from typing import List
import asyncio

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, and_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload
from websockets.asyncio.compatibility import anext

from src.db import get_session
from src.models import Team, TeamMember, User, Stage
from src.models.enums import StageType
from src.models.user import User2Roles
from src.utils.email_utils import email_sender
from src.settings import settings
from src.utils.router_states import team_router_state, user_router_state

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


async def send_team_confirmation_email(session: AsyncSession):
    """
    Отправляет уведомления о подтверждении участия командам
    """
    teams_query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members)
            .selectinload(TeamMember.role),
            selectinload(Team.members)
            .selectinload(TeamMember.status)
        )
    )
    result = await session.execute(teams_query)
    teams = result.scalars().all()

    active_teams = [team for team in teams if team.get_status() == "active"]
    total_teams = len(active_teams)
    successful_sends = 0
    failed_sends = 0

    logging.info(f"Начало рассылки уведомлений о подтверждении участия. Всего команд: {total_teams}")
    start_time = datetime.now()

    for i, team in enumerate(active_teams, 1):
        team_members = [
            member.user for member in team.members
            if member.status_id == team_router_state.accepted_status_id
        ]

        for member in team_members:
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
                                            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-bottom: 30px;">
                                                <tr>
                                                    <td align="center">
                                                        <h1 style="color: #2196F3; font-size: 24px; margin: 0;">Подтверждение участия в хакатоне</h1>
                                                    </td>
                                                </tr>
                                            </table>
                                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Здравствуйте, {member.full_name}!</p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Ваша команда "{team.team_name}" успешно зарегистрирована для участия в хакатоне.</p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Состав команды:</p>
                                                        <ul style="list-style: none; padding: 0;">
                                                            {
            ''.join([
                f'<li style="margin: 5px 0;">{tm.user.full_name} ({tm.role.name})</li>'
                for tm in team.members
                if tm.status_id == team_router_state.accepted_status_id
            ])
            }
                                                        </ul>
                                                    </td>
                                                </tr>
                                            </table>
                                            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 30px;">
                                                <tr>
                                                    <td align="center" style="color: #666666; font-size: 14px;">
                                                        <p style="margin: 0;">Это автоматическое уведомление, пожалуйста, не отвечайте на него.</p>
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

            try:
                success = email_sender.send_email(
                    to_email=member.email,
                    subject="Подтверждение участия в хакатоне",
                    body=html_content,
                    is_html=True
                )
                if success:
                    successful_sends += 1
                    logging.info(
                        f"[Команда {i}/{total_teams}] Отправлено уведомление участнику {member.full_name} ({member.email})")
                else:
                    failed_sends += 1
                    logging.error(
                        f"[Команда {i}/{total_teams}] Ошибка отправки участнику {member.full_name} ({member.email})")
            except Exception as e:
                failed_sends += 1
                logging.error(
                    f"[Команда {i}/{total_teams}] Исключение при отправке участнику {member.full_name} ({member.email}): {str(e)}")

            await asyncio.sleep(2)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    logging.info(f"""
Рассылка уведомлений о подтверждении участия завершена!
Время выполнения: {duration:.2f} секунд
Всего команд: {total_teams}
Успешно отправлено: {successful_sends}
Ошибок отправки: {failed_sends}
    """)


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
                                                <p style="margin: 0;">Для завершения регистрации нажмите на кнопку:</p>
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
                                                <p style="margin: 10px 0 0 0;">или перейдите по ссылке: <a href="{confirmation_link}" style="color: #2196F3;">{confirmation_link}</a></p>
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


async def send_status_change_email(user: User, new_status: str, comment: str = None):
    """Отправляет email с уведомлением об изменении статуса пользователя"""

    status_descriptions = {
        "pending": "на рассмотрении",
        "approved": "одобрен",
        "need_update": "требует обновления",
        "PENDING": "на рассмотрении",
        "APPROVED": "одобрен",
        "NEED_UPDATE": "требует обновления"
    }

    status_key = new_status.lower()
    status_text = status_descriptions.get(status_key, new_status)

    comment_block = ""
    if comment:
        comment_block = f"""
        <tr>
            <td align="center" style="padding: 20px 0; background-color: #f5f5f5; border-radius: 4px;">
                <h3 style="margin: 0 0 10px 0;">Комментарий:</h3>
                <p style="margin: 0;">{comment}</p>
            </td>
        </tr>
        """

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
                                                <h1 style="color: #2196F3; font-size: 24px; margin: 0;">Изменение статуса участника</h1>
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
                                                <p style="margin: 0;">Ваш статус участника был изменен на "{status_text}".</p>
                                            </td>
                                        </tr>
                                        {comment_block}
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
                                    </table>

                                    <!-- Footer -->
                                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 30px;">
                                        <tr>
                                            <td align="center" style="color: #666666; font-size: 14px;">
                                                <p style="margin: 0;">Это автоматическое уведомление, пожалуйста, не отвечайте на него.</p>
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
        subject="Изменение статуса участника",
        body=html_content,
        is_html=True
    )


async def send_hackathon_consultation_notification(session: AsyncSession):
    """
    Фоновая задача для рассылки уведомлений о консультации хакатона
    всем участникам и менторам с задержкой между отправками
    """
    users_query = (
        select(User)
        .distinct()
        .join(User2Roles)
        .where(
            User2Roles.role_id.in_([
                user_router_state.participant_role_id,
                user_router_state.mentor_role_id
            ])
        )
    )

    result = await session.execute(users_query)
    users = result.scalars().all()

    total_users = len(users)
    successful_sends = 0
    failed_sends = 0

    logging.info(f"Начало рассылки уведомлений об открытии хакатона. Всего получателей: {total_users}")
    start_time = datetime.now()

    for i, user in enumerate(users, 1):
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
                                                    <h1 style="color: #2196F3; font-size: 24px; margin: 0;">Консультация по проведению хакатона</h1>
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
                                                    <p style="margin: 0;">Приглашаем вас на онлайн-консультацию по проведению хакатона, которая состоится завтра, <strong>3 апреля, в 9:30 по Московскому времени</strong>.</p>
                                                </td>
                                            </tr>
                                            <tr>
                                                <td align="center" style="padding: 20px 0;">
                                                    <table border="0" cellpadding="0" cellspacing="0">
                                                        <tr>
                                                            <td align="center" bgcolor="#2196F3" style="border-radius: 4px;">
                                                                <a href="https://bigbb2.tyuiu.ru/b/hyc-sjb-5lk-prq" 
                                                                   style="display: inline-block; padding: 12px 24px; color: #ffffff; text-decoration: none; font-weight: bold;">
                                                                    Присоединиться к консультации
                                                                </a>
                                                            </td>
                                                        </tr>
                                                    </table>
                                                </td>
                                            </tr>
                                            <tr>
                                                <td align="center" style="padding: 0 0 20px 0;">
                                                    <p style="margin: 0;">Или перейдите по ссылке: <a href="https://bigbb2.tyuiu.ru/b/hyc-sjb-5lk-prq" style="color: #2196F3;">https://bigbb2.tyuiu.ru/b/hyc-sjb-5lk-prq</a></p>
                                                </td>
                                            </tr>
                                        </table>

                                        <!-- Footer -->
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 30px;">
                                            <tr>
                                                <td align="center" style="color: #666666; font-size: 14px;">
                                                    <p style="margin: 0;">Это автоматическое уведомление, пожалуйста, не отвечайте на него.</p>
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

        try:
            success = email_sender.send_email(
                to_email=user.email,
                subject="Консультация хакатона",
                body=html_content,
                is_html=True
            )
            if success:
                successful_sends += 1
                logging.info(f"[{i}/{total_users}] Отправлено уведомление на email: {user.email}")
            else:
                failed_sends += 1
                logging.error(f"[{i}/{total_users}] Ошибка отправки на email: {user.email}")
        except Exception as e:
            failed_sends += 1
            logging.error(f"[{i}/{total_users}] Исключение при отправке на email {user.email}: {str(e)}")

        if i < total_users:
            await asyncio.sleep(2)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    logging.info(f"""
Рассылка уведомлений об открытии хакатона завершена!
Время выполнения: {duration:.2f} секунд
Всего отправлено: {total_users}
Успешно: {successful_sends}
Ошибок: {failed_sends}
    """)


async def send_single_hackathon_consultation_notification(user: User):
    """
    Отправляет уведомление об консультации хакатона одному пользователю
    """
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
                                                <h1 style="color: #2196F3; font-size: 24px; margin: 0;">Консультация по проведению хакатона</h1>
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
                                                <p style="margin: 0;">Приглашаем вас на онлайн-консультацию по проведению хакатона, которая состоится завтра, <strong>3 апреля, в 9:30 по Московскому времени</strong>.</p>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding: 20px 0;">
                                                <table border="0" cellpadding="0" cellspacing="0">
                                                    <tr>
                                                        <td align="center" bgcolor="#2196F3" style="border-radius: 4px;">
                                                            <a href="https://bigbb2.tyuiu.ru/b/hyc-sjb-5lk-prq" 
                                                               style="display: inline-block; padding: 12px 24px; color: #ffffff; text-decoration: none; font-weight: bold;">
                                                                Присоединиться к консультации
                                                            </a>
                                                        </td>
                                                    </tr>
                                                </table>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding: 0 0 20px 0;">
                                                <p style="margin: 0;">Или перейдите по ссылке: <a href="https://bigbb2.tyuiu.ru/b/hyc-sjb-5lk-prq" style="color: #2196F3;">https://bigbb2.tyuiu.ru/b/hyc-sjb-5lk-prq</a></p>
                                            </td>
                                        </tr>
                                    </table>

                                    <!-- Footer -->
                                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 30px;">
                                        <tr>
                                            <td align="center" style="color: #666666; font-size: 14px;">
                                                <p style="margin: 0;">Это автоматическое уведомление, пожалуйста, не отвечайте на него.</p>
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

    try:
        success = email_sender.send_email(
            to_email=user.email,
            subject="Консультация хакатона",
            body=html_content,
            is_html=True
        )
        if success:
            logging.info(f"Отправлено уведомление о консультации на email: {user.email}")
        else:
            logging.error(f"Ошибка отправки уведомления о консультации на email: {user.email}")
        return success
    except Exception as e:
        logging.error(f"Исключение при отправке уведомления о консультации на email {user.email}: {str(e)}")
        return False


async def send_judge_briefing_notification(session: AsyncSession):
    """
    Фоновая задача для рассылки уведомлений о брифинге
    всем членам жюри с задержкой между отправками
    """
    users_query = (
        select(User)
        .distinct()
        .join(User2Roles)
        .where(
            User2Roles.role_id == user_router_state.judge_role_id
        )
    )

    result = await session.execute(users_query)
    users = result.scalars().all()

    total_users = len(users)
    successful_sends = 0
    failed_sends = 0

    logging.info(f"Начало рассылки уведомлений о брифинге. Всего получателей: {total_users}")
    start_time = datetime.now()

    for i, user in enumerate(users, 1):
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
                                                    <h1 style="color: #2196F3; font-size: 24px; margin: 0;">Брифинг для членов жюри хакатона</h1>
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
                                                    <p style="margin: 0;">Приглашаем вас на брифинг по проведению хакатона, который состоится завтра, <strong>3 апреля, в 8:30 по Московскому времени</strong>.</p>
                                                </td>
                                            </tr>
                                            <tr>
                                                <td align="center" style="padding: 20px 0;">
                                                    <table border="0" cellpadding="0" cellspacing="0">
                                                        <tr>
                                                            <td align="center" bgcolor="#2196F3" style="border-radius: 4px;">
                                                                <a href="https://bigbb2.tyuiu.ru/b/hyc-sjb-5lk-prq" 
                                                                   style="display: inline-block; padding: 12px 24px; color: #ffffff; text-decoration: none; font-weight: bold;">
                                                                    Присоединиться к брифингу
                                                                </a>
                                                            </td>
                                                        </tr>
                                                    </table>
                                                </td>
                                            </tr>
                                            <tr>
                                                <td align="center" style="padding: 0 0 20px 0;">
                                                    <p style="margin: 0;">Или перейдите по ссылке: <a href="https://bigbb2.tyuiu.ru/b/hyc-sjb-5lk-prq" style="color: #2196F3;">https://bigbb2.tyuiu.ru/b/hyc-sjb-5lk-prq</a></p>
                                                </td>
                                            </tr>
                                        </table>

                                        <!-- Footer -->
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 30px;">
                                            <tr>
                                                <td align="center" style="color: #666666; font-size: 14px;">
                                                    <p style="margin: 0;">Это автоматическое уведомление, пожалуйста, не отвечайте на него.</p>
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

        try:
            success = email_sender.send_email(
                to_email=user.email,
                subject="Брифинг для членов жюри хакатона",
                body=html_content,
                is_html=True
            )
            if success:
                successful_sends += 1
                logging.info(f"[{i}/{total_users}] Отправлено уведомление на email: {user.email}")
            else:
                failed_sends += 1
                logging.error(f"[{i}/{total_users}] Ошибка отправки на email: {user.email}")
        except Exception as e:
            failed_sends += 1
            logging.error(f"[{i}/{total_users}] Исключение при отправке на email {user.email}: {str(e)}")

        if i < total_users:
            await asyncio.sleep(2)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    logging.info(f"""
Рассылка уведомлений о брифинге завершена!
Время выполнения: {duration:.2f} секунд
Всего отправлено: {total_users}
Успешно: {successful_sends}
Ошибок: {failed_sends}
    """)


async def send_single_judge_briefing_notification(user: User):
    """
    Отправляет уведомление о брифинге одному члену жюри
    """
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
                                                <h1 style="color: #2196F3; font-size: 24px; margin: 0;">Брифинг для членов жюри хакатона</h1>
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
                                                <p style="margin: 0;">Приглашаем вас на брифинг по проведению хакатона, который состоится завтра, <strong>3 апреля, в 8:30 по Московскому времени</strong>.</p>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding: 20px 0;">
                                                <table border="0" cellpadding="0" cellspacing="0">
                                                    <tr>
                                                        <td align="center" bgcolor="#2196F3" style="border-radius: 4px;">
                                                            <a href="https://bigbb2.tyuiu.ru/b/hyc-sjb-5lk-prq" 
                                                               style="display: inline-block; padding: 12px 24px; color: #ffffff; text-decoration: none; font-weight: bold;">
                                                                Присоединиться к брифингу
                                                            </a>
                                                        </td>
                                                    </tr>
                                                </table>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td align="center" style="padding: 0 0 20px 0;">
                                                <p style="margin: 0;">Или перейдите по ссылке: <a href="https://bigbb2.tyuiu.ru/b/hyc-sjb-5lk-prq" style="color: #2196F3;">https://bigbb2.tyuiu.ru/b/hyc-sjb-5lk-prq</a></p>
                                            </td>
                                        </tr>
                                    </table>

                                    <!-- Footer -->
                                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 30px;">
                                        <tr>
                                            <td align="center" style="color: #666666; font-size: 14px;">
                                                <p style="margin: 0;">Это автоматическое уведомление, пожалуйста, не отвечайте на него.</p>
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

    try:
        success = email_sender.send_email(
            to_email=user.email,
            subject="Брифинг для членов жюри хакатона",
            body=html_content,
            is_html=True
        )
        if success:
            logging.info(f"Отправлено уведомление о брифинге на email: {user.email}")
        else:
            logging.error(f"Ошибка отправки уведомления о брифинге на email: {user.email}")
        return success
    except Exception as e:
        logging.error(f"Исключение при отправке уведомления о брифинге на email {user.email}: {str(e)}")
        return False


async def send_registration_closed_notification(session: AsyncSession):
    """
    Отправляет уведомление о закрытии регистрации и публикации исходных данных
    всем активным командам
    """
    teams_query = (
        select(Team)
        .options(
            joinedload(Team.members)
            .joinedload(TeamMember.status),
            joinedload(Team.members)
            .joinedload(TeamMember.role),
            joinedload(Team.members)
            .joinedload(TeamMember.user)
            .joinedload(User.current_status)
        )
    )

    result = await session.execute(teams_query)
    all_teams = result.unique().scalars().all()

    active_teams = [team for team in all_teams if team.get_status() == "active"]

    total_teams = len(active_teams)
    successful_sends = 0
    failed_sends = 0

    logging.info(f"Начало рассылки уведомлений о закрытии регистрации. Всего активных команд: {total_teams}")
    start_time = datetime.now()

    for i, team in enumerate(active_teams, 1):
        team_members = team.get_active_members()

        for member in team_members:
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
                                                        <h1 style="color: #2196F3; font-size: 24px; margin: 0;">Регистрация на хакатон закрыта</h1>
                                                    </td>
                                                </tr>
                                            </table>

                                            <!-- Content -->
                                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Здравствуйте, {member.user.full_name}!</p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Регистрация на хакатон завершена. В разделе "Моя команда" опубликованы исходные данные для выполнения задания.</p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 20px 0;">
                                                        <table border="0" cellpadding="0" cellspacing="0">
                                                            <tr>
                                                                <td align="center" bgcolor="#2196F3" style="border-radius: 4px;">
                                                                    <a href="{settings.base_url}/profile/team" 
                                                                       style="display: inline-block; padding: 12px 24px; color: #ffffff; text-decoration: none; font-weight: bold;">
                                                                        Перейти к исходным данным
                                                                    </a>
                                                                </td>
                                                            </tr>
                                                        </table>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Команда: {team.team_name}</p>
                                                    </td>
                                                </tr>
                                            </table>

                                            <!-- Footer -->
                                            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 30px;">
                                                <tr>
                                                    <td align="center" style="color: #666666; font-size: 14px;">
                                                        <p style="margin: 0;">Это автоматическое уведомление, пожалуйста, не отвечайте на него.</p>
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

            try:
                success = email_sender.send_email(
                    to_email=member.user.email,
                    subject="Регистрация закрыта - опубликованы исходные данные",
                    body=html_content,
                    is_html=True
                )
                if success:
                    successful_sends += 1
                    logging.info(
                        f"[Команда {i}/{total_teams}] Отправлено уведомление участнику {member.user.full_name} ({member.user.email})")
                else:
                    failed_sends += 1
                    logging.error(
                        f"[Команда {i}/{total_teams}] Ошибка отправки участнику {member.user.full_name} ({member.user.email})")
            except Exception as e:
                failed_sends += 1
                logging.error(
                    f"[Команда {i}/{total_teams}] Исключение при отправке участнику {member.user.full_name} ({member.user.email}): {str(e)}")

            await asyncio.sleep(2)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    logging.info(f"""
Рассылка уведомлений о закрытии регистрации завершена!
Время выполнения: {duration:.2f} секунд
Всего команд: {total_teams}
Успешно отправлено: {successful_sends}
Ошибок отправки: {failed_sends}
    """)


async def send_task_update_notification(session: AsyncSession):
    """
    Отправляет уведомление о публикации дополнения к исходным данным
    всем участникам активных команд
    """
    logging.info("Начинаю рассылку уведомлений о дополнении к исходным данным")
    start_time = datetime.now()

    teams_query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members)
            .selectinload(TeamMember.role),
            selectinload(Team.members)
            .selectinload(TeamMember.status)
        )
    )
    result = await session.execute(teams_query)
    teams = result.scalars().all()

    active_teams = [team for team in teams if team.get_status() == "active"]
    total_teams = len(active_teams)
    successful_sends = 0
    failed_sends = 0

    logging.info(f"Найдено активных команд: {total_teams}")

    for i, team in enumerate(active_teams, 1):
        logging.info(f"Обработка команды {i}/{total_teams}: {team.team_name}")

        team_members = [
            member for member in team.members
            if member.status_id == team_router_state.accepted_status_id
        ]

        for member in team_members:
            html_content = f"""
            <!DOCTYPE html>
            <html>
                <head>
                    <meta charset="utf-8">
                    <!-- Стили -->
                    <style>
                        body {{
                            margin: 0;
                            padding: 0;
                            background-color: #f4f4f4;
                            font-family: Arial, sans-serif;
                        }}
                    </style>
                </head>
                <body>
                    <table border="0" cellpadding="0" cellspacing="0" width="100%">
                        <tr>
                            <td align="center" style="padding: 40px 0;">
                                <table border="0" cellpadding="0" cellspacing="0" width="600" style="background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                                    <tr>
                                        <td style="padding: 40px 30px;">
                                            <!-- Header -->
                                            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-bottom: 30px;">
                                                <tr>
                                                    <td align="center">
                                                        <h1 style="color: #2196F3; font-size: 24px; margin: 0;">Дополнение к исходным данным</h1>
                                                    </td>
                                                </tr>
                                            </table>

                                            <!-- Content -->
                                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Здравствуйте, {member.user.full_name}!</p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">На сайте хакатона опубликовано дополнение к исходным данным. Ознакомьтесь с обновленной информацией в личном кабинете.</p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 20px 0;">
                                                        <table border="0" cellpadding="0" cellspacing="0">
                                                            <tr>
                                                                <td align="center" bgcolor="#2196F3" style="border-radius: 4px;">
                                                                    <a href="{settings.base_url}/profile/team" 
                                                                       style="display: inline-block; padding: 12px 24px; color: #ffffff; text-decoration: none; font-weight: bold;">
                                                                        Перейти к дополнению
                                                                    </a>
                                                                </td>
                                                            </tr>
                                                        </table>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Команда: {team.team_name}</p>
                                                    </td>
                                                </tr>
                                            </table>

                                            <!-- Footer -->
                                            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 30px;">
                                                <tr>
                                                    <td align="center" style="color: #666666; font-size: 14px;">
                                                        <p style="margin: 0;">Это автоматическое уведомление, пожалуйста, не отвечайте на него.</p>
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

            try:
                success = email_sender.send_email(
                    to_email=member.user.email,
                    subject="Опубликовано дополнение к исходным данным",
                    body=html_content,
                    is_html=True
                )
                if success:
                    successful_sends += 1
                    logging.info(
                        f"[Команда {i}/{total_teams}] Отправлено уведомление участнику {member.user.full_name} ({member.user.email})")
                else:
                    failed_sends += 1
                    logging.error(
                        f"[Команда {i}/{total_teams}] Ошибка отправки участнику {member.user.full_name} ({member.user.email})")
            except Exception as e:
                failed_sends += 1
                logging.error(
                    f"[Команда {i}/{total_teams}] Исключение при отправке участнику {member.user.full_name} ({member.user.email}): {str(e)}")

            await asyncio.sleep(2)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    logging.info(f"""
Рассылка уведомлений о дополнении к исходным данным завершена!
Время выполнения: {duration:.2f} секунд
Всего команд: {total_teams}
Успешно отправлено: {successful_sends}
Ошибок отправки: {failed_sends}
    """)


async def send_hackathon_opening_notification(session: AsyncSession):
    """
    Отправляет уведомление об открытии хакатона всем участникам активных команд
    """
    teams_query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members)
            .selectinload(TeamMember.role),
            selectinload(Team.members)
            .selectinload(TeamMember.status)
        )
    )
    result = await session.execute(teams_query)
    teams = result.scalars().all()

    active_teams = [team for team in teams if team.get_status() == "active"]
    total_teams = len(active_teams)
    successful_sends = 0
    failed_sends = 0

    logging.info(f"Начало рассылки уведомлений об открытии хакатона. Всего команд: {total_teams}")
    start_time = datetime.now()

    for i, team in enumerate(active_teams, 1):
        logging.info(f"Обработка команды {i}/{total_teams}: {team.team_name}")

        team_members = [
            member.user for member in team.members
            if member.status_id == team_router_state.accepted_status_id
        ]

        for member in team_members:
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
                                                        <h1 style="color: #2196F3; font-size: 24px; margin: 0;">Открытие хакатона</h1>
                                                    </td>
                                                </tr>
                                            </table>

                                            <!-- Content -->
                                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Здравствуйте, {member.full_name}!</p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Приглашаем вас на онлайн-открытие хакатона, которое состоится завтра, <strong>9 апреля, в 9:00 по Московскому времени</strong>.</p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 20px 0;">
                                                        <table border="0" cellpadding="0" cellspacing="0">
                                                            <tr>
                                                                <td align="center" bgcolor="#2196F3" style="border-radius: 4px;">
                                                                    <a href="https://bigbb2.tyuiu.ru/b/hyc-sjb-5lk-prq" 
                                                                       style="display: inline-block; padding: 12px 24px; color: #ffffff; text-decoration: none; font-weight: bold;">
                                                                        Присоединиться к открытию
                                                                    </a>
                                                                </td>
                                                            </tr>
                                                        </table>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Или перейдите по ссылке: <a href="https://bigbb2.tyuiu.ru/b/hyc-sjb-5lk-prq" style="color: #2196F3;">https://bigbb2.tyuiu.ru/b/hyc-sjb-5lk-prq</a></p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Команда: {team.team_name}</p>
                                                    </td>
                                                </tr>
                                            </table>

                                            <!-- Footer -->
                                            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 30px;">
                                                <tr>
                                                    <td align="center" style="color: #666666; font-size: 14px;">
                                                        <p style="margin: 0;">Это автоматическое уведомление, пожалуйста, не отвечайте на него.</p>
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

            try:
                success = email_sender.send_email(
                    to_email=member.email,
                    subject="Открытие хакатона",
                    body=html_content,
                    is_html=True
                )
                if success:
                    successful_sends += 1
                    logging.info(
                        f"[Команда {i}/{total_teams}] Отправлено уведомление участнику {member.full_name} ({member.email})")
                else:
                    failed_sends += 1
                    logging.error(
                        f"[Команда {i}/{total_teams}] Ошибка отправки участнику {member.full_name} ({member.email})")
            except Exception as e:
                failed_sends += 1
                logging.error(
                    f"[Команда {i}/{total_teams}] Исключение при отправке участнику {member.full_name} ({member.email}): {str(e)}")

            await asyncio.sleep(2)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    logging.info(f"""
Рассылка уведомлений об открытии хакатона завершена!
Время выполнения: {duration:.2f} секунд
Всего команд: {total_teams}
Успешно отправлено: {successful_sends}
Ошибок отправки: {failed_sends}
""")


async def send_hackathon_started_notification(session: AsyncSession):
    """
    Отправляет уведомление о начале хакатона и публикации тестовых данных
    всем активным командам
    """
    teams_query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members)
            .selectinload(TeamMember.role),
            selectinload(Team.members)
            .selectinload(TeamMember.status)
        )
    )
    result = await session.execute(teams_query)
    teams = result.scalars().all()

    active_teams = [team for team in teams if team.get_status() == "active"]
    total_teams = len(active_teams)
    successful_sends = 0
    failed_sends = 0

    logging.info(f"Начало рассылки уведомлений о старте хакатона. Всего команд: {total_teams}")
    start_time = datetime.now()

    for i, team in enumerate(active_teams, 1):
        team_members = [
            member.user for member in team.members
            if member.status_id == team_router_state.accepted_status_id
        ]

        for member in team_members:
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
                                                        <h1 style="color: #2196F3; font-size: 24px; margin: 0;">Хакатон начался!</h1>
                                                    </td>
                                                </tr>
                                            </table>

                                            <!-- Content -->
                                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Здравствуйте, {member.full_name}!</p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Хакатон официально стартовал! В разделе "Моя команда" опубликованы тестовые данные для выполнения задания.</p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Желаем вашей команде продуктивной работы и успешного выполнения задания!</p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 20px 0;">
                                                        <table border="0" cellpadding="0" cellspacing="0">
                                                            <tr>
                                                                <td align="center" bgcolor="#2196F3" style="border-radius: 4px;">
                                                                    <a href="{settings.base_url}/profile/team" 
                                                                       style="display: inline-block; padding: 12px 24px; color: #ffffff; text-decoration: none; font-weight: bold;">
                                                                        Перейти к тестовым данным
                                                                    </a>
                                                                </td>
                                                            </tr>
                                                        </table>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Команда: {team.team_name}</p>
                                                    </td>
                                                </tr>
                                            </table>

                                            <!-- Footer -->
                                            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 30px;">
                                                <tr>
                                                    <td align="center" style="color: #666666; font-size: 14px;">
                                                        <p style="margin: 0;">Это автоматическое уведомление, пожалуйста, не отвечайте на него.</p>
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

            try:
                success = email_sender.send_email(
                    to_email=member.email,
                    subject="Хакатон начался! Опубликованы тестовые данные",
                    body=html_content,
                    is_html=True
                )
                if success:
                    successful_sends += 1
                    logging.info(
                        f"[Команда {i}/{total_teams}] Отправлено уведомление участнику {member.full_name} ({member.email})")
                else:
                    failed_sends += 1
                    logging.error(
                        f"[Команда {i}/{total_teams}] Ошибка отправки участнику {member.full_name} ({member.email})")
            except Exception as e:
                failed_sends += 1
                logging.error(
                    f"[Команда {i}/{total_teams}] Исключение при отправке участнику {member.full_name} ({member.email}): {str(e)}")

            await asyncio.sleep(2)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    logging.info(f"""
Рассылка уведомлений о начале хакатона завершена!
Время выполнения: {duration:.2f} секунд
Всего команд: {total_teams}
Успешно отправлено: {successful_sends}
Ошибок отправки: {failed_sends}
""")


async def send_solution_submission_notification(session: AsyncSession):
    """
    Отправляет уведомление о скором завершении хакатона
    всем активным командам
    """
    teams_query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members)
            .selectinload(TeamMember.role),
            selectinload(Team.members)
            .selectinload(TeamMember.status)
        )
    )
    result = await session.execute(teams_query)
    teams = result.scalars().all()

    active_teams = [team for team in teams if team.get_status() == "active"]
    total_teams = len(active_teams)
    successful_sends = 0
    failed_sends = 0

    logging.info(f"Начало рассылки уведомлений о завершении хакатона. Всего команд: {total_teams}")
    start_time = datetime.now()

    for i, team in enumerate(active_teams, 1):
        team_members = [
            member.user for member in team.members
            if member.status_id == team_router_state.accepted_status_id
        ]

        for member in team_members:
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
                                                        <h1 style="color: #2196F3; font-size: 24px; margin: 0;">Завершение хакатона через 30 минут</h1>
                                                    </td>
                                                </tr>
                                            </table>

                                            <!-- Content -->
                                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Здравствуйте, {member.full_name}!</p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">До окончания хакатона осталось менее 30 минут. Просим вас убедиться, что все материалы вашего решения прикреплены в личном кабинете.</p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 20px 0;">
                                                        <table border="0" cellpadding="0" cellspacing="0">
                                                            <tr>
                                                                <td align="center" bgcolor="#2196F3" style="border-radius: 4px;">
                                                                    <a href="{settings.base_url}/profile/team" 
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
                                                        <p style="margin: 0;">Команда: {team.team_name}</p>
                                                    </td>
                                                </tr>
                                            </table>

                                            <!-- Footer -->
                                            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 30px;">
                                                <tr>
                                                    <td align="center" style="color: #666666; font-size: 14px;">
                                                        <p style="margin: 0;">Это автоматическое уведомление, пожалуйста, не отвечайте на него.</p>
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

            try:
                success = email_sender.send_email(
                    to_email=member.email,
                    subject="Завершение хакатона через 30 минут",
                    body=html_content,
                    is_html=True
                )
                if success:
                    successful_sends += 1
                    logging.info(
                        f"[Команда {i}/{total_teams}] Отправлено уведомление участнику {member.full_name} ({member.email})")
                else:
                    failed_sends += 1
                    logging.error(
                        f"[Команда {i}/{total_teams}] Ошибка отправки участнику {member.full_name} ({member.email})")
            except Exception as e:
                failed_sends += 1
                logging.error(
                    f"[Команда {i}/{total_teams}] Исключение при отправке участнику {member.full_name} ({member.email}): {str(e)}")

            await asyncio.sleep(2)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    logging.info(f"""
Рассылка уведомлений о завершении хакатона завершена!
Время выполнения: {duration:.2f} секунд
Всего команд: {total_teams}
Успешно отправлено: {successful_sends}
Ошибок отправки: {failed_sends}
""")


async def send_hackathon_ended_notification(session: AsyncSession):
    """
    Отправляет уведомление о завершении хакатона
    всем активным командам
    """
    teams_query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members)
            .selectinload(TeamMember.role),
            selectinload(Team.members)
            .selectinload(TeamMember.status)
        )
    )
    result = await session.execute(teams_query)
    teams = result.scalars().all()

    active_teams = [team for team in teams if team.get_status() == "active"]
    total_teams = len(active_teams)
    successful_sends = 0
    failed_sends = 0

    logging.info(f"Начало рассылки уведомлений об окончании хакатона. Всего команд: {total_teams}")
    start_time = datetime.now()

    for i, team in enumerate(active_teams, 1):
        team_members = [
            member.user for member in team.members
            if member.status_id == team_router_state.accepted_status_id
        ]

        for member in team_members:
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
                                                        <h1 style="color: #2196F3; font-size: 24px; margin: 0;">Хакатон завершен</h1>
                                                    </td>
                                                </tr>
                                            </table>

                                            <!-- Content -->
                                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Здравствуйте, {member.full_name}!</p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Хакатон официально завершен. В настоящее время жюри приступает к проверке решений команд.</p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Благодарим вас за участие! О результатах проверки и дальнейших шагах мы сообщим дополнительно.</p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Команда: {team.team_name}</p>
                                                    </td>
                                                </tr>
                                            </table>

                                            <!-- Footer -->
                                            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 30px;">
                                                <tr>
                                                    <td align="center" style="color: #666666; font-size: 14px;">
                                                        <p style="margin: 0;">Это автоматическое уведомление, пожалуйста, не отвечайте на него.</p>
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

            try:
                success = email_sender.send_email(
                    to_email=member.email,
                    subject="Хакатон завершен",
                    body=html_content,
                    is_html=True
                )
                if success:
                    successful_sends += 1
                    logging.info(
                        f"[Команда {i}/{total_teams}] Отправлено уведомление участнику {member.full_name} ({member.email})")
                else:
                    failed_sends += 1
                    logging.error(
                        f"[Команда {i}/{total_teams}] Ошибка отправки участнику {member.full_name} ({member.email})")
            except Exception as e:
                failed_sends += 1
                logging.error(
                    f"[Команда {i}/{total_teams}] Исключение при отправке участнику {member.full_name} ({member.email}): {str(e)}")

            await asyncio.sleep(2)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    logging.info(f"""
Рассылка уведомлений об окончании хакатона завершена!
Время выполнения: {duration:.2f} секунд
Всего команд: {total_teams}
Успешно отправлено: {successful_sends}
Ошибок отправки: {failed_sends}
""")


async def send_judge_opening_notification(session: AsyncSession):
    """
    Отправляет уведомление об очном открытии хакатона всем членам жюри
    """
    users_query = (
        select(User)
        .distinct()
        .join(User2Roles)
        .where(
            User2Roles.role_id == user_router_state.judge_role_id
        )
    )

    result = await session.execute(users_query)
    users = result.scalars().all()

    total_users = len(users)
    successful_sends = 0
    failed_sends = 0

    logging.info(
        f"Начало рассылки уведомлений об очном открытии хакатона членам жюри. Всего получателей: {total_users}")
    start_time = datetime.now()

    for i, user in enumerate(users, 1):
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
                                                    <h1 style="color: #2196F3; font-size: 24px; margin: 0;">Очное открытие хакатона</h1>
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
                                                    <p style="margin: 0;">Приглашаем вас на очное открытие хакатона, которое состоится сегодня, <strong>в 10:30 по тюменскому времени</strong>.</p>
                                                </td>
                                            </tr>
                                            <tr>
                                                <td align="center" style="padding: 0 0 20px 0;">
                                                    <p style="margin: 0;">Место проведения: <strong>ул. Володарского, 38, аудитория 237</strong></p>
                                                </td>
                                            </tr>
                                            <tr>
                                                <td align="center" style="padding: 0 0 20px 0;">
                                                    <p style="margin: 0;">Просим вас прибыть за 10-15 минут до начала мероприятия.</p>
                                                </td>
                                            </tr>
                                        </table>

                                        <!-- Footer -->
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 30px;">
                                            <tr>
                                                <td align="center" style="color: #666666; font-size: 14px;">
                                                    <p style="margin: 0;">Это автоматическое уведомление, пожалуйста, не отвечайте на него.</p>
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

        try:
            success = email_sender.send_email(
                to_email=user.email,
                subject="Очное открытие хакатона",
                body=html_content,
                is_html=True
            )
            if success:
                successful_sends += 1
                logging.info(f"[{i}/{total_users}] Отправлено уведомление на email: {user.email}")
            else:
                failed_sends += 1
                logging.error(f"[{i}/{total_users}] Ошибка отправки на email: {user.email}")
        except Exception as e:
            failed_sends += 1
            logging.error(f"[{i}/{total_users}] Исключение при отправке на email {user.email}: {str(e)}")

        if i < total_users:
            await asyncio.sleep(2)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    logging.info(f"""
Рассылка уведомлений об очном открытии хакатона завершена!
Время выполнения: {duration:.2f} секунд
Всего получателей: {total_users}
Успешно: {successful_sends}
Ошибок: {failed_sends}
    """)


async def send_defense_schedule_notification(session: AsyncSession):
    """
    Отправляет уведомление о защите проектов
    всем активным командам
    """
    teams_query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members)
            .selectinload(TeamMember.role),
            selectinload(Team.members)
            .selectinload(TeamMember.status)
        )
    )
    result = await session.execute(teams_query)
    teams = result.scalars().all()

    active_teams = [team for team in teams if team.get_status() == "active"]
    total_teams = len(active_teams)
    successful_sends = 0
    failed_sends = 0

    logging.info(f"Начало рассылки уведомлений о защите проектов. Всего команд: {total_teams}")
    start_time = datetime.now()

    for i, team in enumerate(active_teams, 1):
        team_members = [
            member.user for member in team.members
            if member.status_id == team_router_state.accepted_status_id
        ]

        for member in team_members:
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
                                                        <h1 style="color: #2196F3; font-size: 24px; margin: 0;">Защита проектов</h1>
                                                    </td>
                                                </tr>
                                            </table>

                                            <!-- Content -->
                                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Здравствуйте, {member.full_name}!</p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Просим подключиться в <strong>8:30 (Мск) 11.04.25</strong> для проверки связи.</p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Во время защиты необходимо продемонстрировать работу своей программы. В докладе перечислить результаты моделирования.</p>
                                                        <p style="margin: 10px 0 0 0;">BigBlueButton позволяет осуществлять демонстрацию экрана.</p>
                                                        <p style="margin: 10px 0 0 0;"><strong>Продолжительность доклада не более 5 минут.</strong></p>
                                                        <p style="margin: 10px 0 0 0;"><strong>График защит представлен на главной странице сайта.</strong></p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 20px 0;">
                                                        <table border="0" cellpadding="0" cellspacing="0">
                                                            <tr>
                                                                <td align="center" bgcolor="#2196F3" style="border-radius: 4px;">
                                                                    <a href="https://bigbb2.tyuiu.ru/b/hyc-sjb-5lk-prq" 
                                                                       style="display: inline-block; padding: 12px 24px; color: #ffffff; text-decoration: none; font-weight: bold;">
                                                                        Присоединиться к защите
                                                                    </a>
                                                                </td>
                                                            </tr>
                                                        </table>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Команда: {team.team_name}</p>
                                                    </td>
                                                </tr>
                                            </table>

                                            <!-- Footer -->
                                            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 30px;">
                                                <tr>
                                                    <td align="center" style="color: #666666; font-size: 14px;">
                                                        <p style="margin: 0;">Это автоматическое уведомление, пожалуйста, не отвечайте на него.</p>
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

            try:
                success = email_sender.send_email(
                    to_email=member.email,
                    subject="Защита проектов - Информация о подключении",
                    body=html_content,
                    is_html=True
                )
                if success:
                    successful_sends += 1
                    logging.info(
                        f"[Команда {i}/{total_teams}] Отправлено уведомление участнику {member.full_name} ({member.email})")
                else:
                    failed_sends += 1
                    logging.error(
                        f"[Команда {i}/{total_teams}] Ошибка отправки участнику {member.full_name} ({member.email})")
            except Exception as e:
                failed_sends += 1
                logging.error(
                    f"[Команда {i}/{total_teams}] Исключение при отправке участнику {member.full_name} ({member.email}): {str(e)}")

            await asyncio.sleep(2)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    logging.info(f"""
Рассылка уведомлений о защите проектов завершена!
Время выполнения: {duration:.2f} секунд
Всего команд: {total_teams}
Успешно отправлено: {successful_sends}
Ошибок отправки: {failed_sends}
""")


async def send_closing_ceremony_notification(session: AsyncSession):
    """
    Отправляет уведомление о торжественном закрытии хакатона всем активным командам
    """
    teams_query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members)
            .selectinload(TeamMember.role),
            selectinload(Team.members)
            .selectinload(TeamMember.status)
        )
    )
    result = await session.execute(teams_query)
    teams = result.scalars().all()

    active_teams = [team for team in teams if team.get_status() == "active"]
    total_teams = len(active_teams)
    successful_sends = 0
    failed_sends = 0

    logging.info(f"Начало рассылки уведомлений о торжественном закрытии. Всего команд: {total_teams}")
    start_time = datetime.now()

    for i, team in enumerate(active_teams, 1):
        team_members = [
            member.user for member in team.members
            if member.status_id == team_router_state.accepted_status_id
        ]

        for member in team_members:
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
                                                    <h1 style="color: #2196F3; font-size: 24px; margin: 0;">Торжественное закрытие хакатона</h1>
                                                </td>
                                            </tr>
                                        </table>
                                        <!-- Content -->
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                            <tr>
                                                <td align="center" style="padding: 0 0 20px 0;">
                                                    <p style="margin: 0;">Здравствуйте, {member.full_name}!</p>
                                                </td>
                                            </tr>
                                            <tr>
                                                <td align="center" style="padding: 0 0 20px 0;">
                                                    <p style="margin: 0;">Приглашаем вас принять участие в торжественном закрытии хакатона, которое состоится сегодня в <strong>14:00 (Мск)</strong>.</p>
                                                </td>
                                            </tr>
                                            <tr>
                                                <td align="center" style="padding: 20px 0;">
                                                    <table border="0" cellpadding="0" cellspacing="0">
                                                        <tr>
                                                            <td align="center" bgcolor="#2196F3" style="border-radius: 4px;">
                                                                <a href="https://bigbb2.tyuiu.ru/b/hyc-sjb-5lk-prq" 
                                                                   style="display: inline-block; padding: 12px 24px; color: #ffffff; text-decoration: none; font-weight: bold;">
                                                                    Присоединиться к церемонии закрытия
                                                                </a>
                                                            </td>
                                                        </tr>
                                                    </table>
                                                </td>
                                            </tr>
                                            <tr>
                                                <td align="center" style="padding: 0 0 20px 0;">
                                                    <p style="margin: 0;">Команда: {team.team_name}</p>
                                                </td>
                                            </tr>
                                        </table>
                                        <!-- Footer -->
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 30px;">
                                            <tr>
                                                <td align="center" style="color: #666666; font-size: 14px;">
                                                    <p style="margin: 0;">Это автоматическое уведомление, пожалуйста, не отвечайте на него.</p>
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

            try:
                success = email_sender.send_email(
                    to_email=member.email,
                    subject="Торжественное закрытие хакатона",
                    body=html_content,
                    is_html=True
                )
                if success:
                    successful_sends += 1
                    logging.info(
                        f"[Команда {i}/{total_teams}] Отправлено уведомление участнику {member.full_name} ({member.email})"
                    )
                else:
                    failed_sends += 1
                    logging.error(
                        f"[Команда {i}/{total_teams}] Ошибка отправки участнику {member.full_name} ({member.email})"
                    )
            except Exception as e:
                failed_sends += 1
                logging.error(
                    f"[Команда {i}/{total_teams}] Исключение при отправке участнику {member.full_name} ({member.email}): {str(e)}"
                )

            await asyncio.sleep(2)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    logging.info(f"""
    Рассылка уведомлений о торжественном закрытии завершена!
    Время выполнения: {duration:.2f} секунд
    Всего команд: {total_teams}
    Успешно отправлено: {successful_sends}
    Ошибок отправки: {failed_sends}
    """)


async def check_and_start_hackathon():
    """
    Меняет stage на task_distribution (3 этап) и отправляет уведомления
    """
    logging.info("Смена этапа на task_distribution")

    session: AsyncSession = await anext(get_session())

    try:
        result = await session.execute(
            select(Stage).where(Stage.is_active == True)
        )
        current_stage = result.scalar_one_or_none()

        if current_stage:
            result = await session.execute(
                select(Stage).where(Stage.type == StageType.TASK_DISTRIBUTION.value)
            )
            task_distribution_stage = result.scalar_one_or_none()

            if task_distribution_stage:
                await session.execute(
                    update(Stage)
                    .where(Stage.id == current_stage.id)
                    .values(is_active=False)
                )

                task_distribution_stage.is_active = True

                await session.commit()
                logging.info("Этап успешно изменен на task_distribution")

                await send_hackathon_started_notification(session)
            else:
                logging.error("Этап task_distribution не найден в базе данных")
        else:
            logging.warning("Активный этап не найден")
    except Exception as e:
        logging.error(f"Ошибки при изменении этапа: {str(e)}")
        await session.rollback()
        raise
    finally:
        await session.close()


async def check_and_close_registration():
    """
    Меняет stage с registration на registration_closed и отправляет уведомления
    """
    logging.info("Смена этапа регистрации на регистрация закрыта")

    session: AsyncSession = await anext(get_session())

    try:
        result = await session.execute(
            select(Stage).where(
                and_(
                    Stage.is_active == True,
                    Stage.type == StageType.REGISTRATION.value
                )
            )
        )
        current_stage = result.scalar_one_or_none()

        if current_stage:
            result = await session.execute(
                select(Stage).where(Stage.type == StageType.REGISTRATION_CLOSED.value)
            )
            registration_closed_stage = result.scalar_one_or_none()

            if registration_closed_stage:
                await session.execute(
                    update(Stage)
                    .where(Stage.id == current_stage.id)
                    .values(is_active=False)
                )

                registration_closed_stage.is_active = True

                await session.commit()
                logging.info("Этап регистрации успешно изменен на этап регистрация закрыта")

                await send_registration_closed_notification(session)
            else:
                logging.error("Registration_closed не найден в базе данных")
        else:
            logging.warning("Текущий этап не регистрация, не требуется изменений")
    except Exception as e:
        logging.error(f"Ошибки при изменении этапа: {str(e)}")
        await session.rollback()
        raise
    finally:
        await session.close()


tz = pytz.timezone('Europe/Moscow')
target_date = tz.localize(datetime(2025, 4, 4, 0, 0, 0))
hackathon_start_date = tz.localize(datetime(2025, 4, 9, 9, 30, 0))
solution_submission_date = tz.localize(datetime(2025, 4, 10, 9, 0, 0))
solution_review_date = tz.localize(datetime(2025, 4, 10, 9, 30, 0))


async def check_time_and_close_registration():
    """
    Проверяет время и закрывает регистрацию, если наступила целевая дата
    """
    current_date = datetime.now(tz)
    logging.info(f"Проверка времени. Текущее: {current_date}, Цель: {target_date}")

    if current_date >= target_date:
        logging.info(f"Целевая дата {target_date} достигнута. Выполняю закрытие регистрации.")
        await check_and_close_registration()
        scheduler.remove_job('check_registration_time')
        logging.info("Задача закрытия регистрации выполнена и удалена из планировщика")
    else:
        logging.info(f"Целевая дата еще не достигнута. Ожидаю... Текущее время: {current_date}")


async def check_time_and_start_hackathon():
    """
    Проверяет время и запускает хакатон, если наступила целевая дата.
    При первом запуске рассчитывает точное время следующей проверки.
    """
    current_date = datetime.now(tz)
    logging.info(f"Проверка времени для старта хакатона. Текущее: {current_date}, Цель: {hackathon_start_date}")

    if current_date >= hackathon_start_date:
        logging.info(f"Целевая дата {hackathon_start_date} достигнута. Выполняю запуск хакатона.")
        await check_and_start_hackathon()
        scheduler.remove_job('check_hackathon_start_time')
        logging.info("Задача запуска хакатона выполнена и удалена из планировщика")
    else:
        # Рассчитываем время до следующей минуты
        next_minute = current_date.replace(second=0, microsecond=0) + timedelta(minutes=1)
        delay = (next_minute - current_date).total_seconds()

        if delay > 0:
            logging.info(f"Корректировка расписания. Следующая проверка через {delay:.2f} секунд")

            # Удаляем текущее расписание
            scheduler.remove_job('check_hackathon_start_time')

            # Создаем новое расписание, начиная с следующей минуты
            # scheduler.add_job(
            #     check_time_and_start_hackathon,
            #     trigger=IntervalTrigger(minutes=1),
            #     id='check_hackathon_start_time',
            #     name='Check hackathon start time and switch stage',
            #     next_run_time=next_minute,
            #     replace_existing=True
            # )

        logging.info(f"Целевая дата еще не достигнута. Следующая проверка в {next_minute}")


scheduler = AsyncIOScheduler()

# scheduler.add_job(
#     check_time_and_close_registration,
#     trigger=IntervalTrigger(minutes=1),
#     id='check_registration_time',
#     name='Check registration time and close if needed',
#     replace_existing=True
# )

logging.info(f"Scheduled registration close check job. Целевая дата: {target_date}")


async def check_and_start_solution_submission():
    """
    Меняет stage на solution_submission (4 этап) и отправляет уведомления
    """
    logging.info("Смена этапа на solution_submission")

    session: AsyncSession = await anext(get_session())

    try:
        result = await session.execute(
            select(Stage).where(Stage.is_active == True)
        )
        current_stage = result.scalar_one_or_none()

        if current_stage:
            result = await session.execute(
                select(Stage).where(Stage.type == StageType.SOLUTION_SUBMISSION.value)
            )
            solution_submission_stage = result.scalar_one_or_none()

            if solution_submission_stage:
                await session.execute(
                    update(Stage)
                    .where(Stage.id == current_stage.id)
                    .values(is_active=False)
                )

                solution_submission_stage.is_active = True

                await session.commit()
                logging.info("Этап успешно изменен на solution_submission")

                await send_solution_submission_notification(session)
            else:
                logging.error("Этап solution_submission не найден в базе данных")
        else:
            logging.warning("Активный этап не найден")
    except Exception as e:
        logging.error(f"Ошибки при изменении этапа: {str(e)}")
        await session.rollback()
        raise
    finally:
        await session.close()


async def check_and_start_solution_submission():
    """
    Меняет stage на solution_submission (4 этап) и отправляет уведомления
    """
    logging.info("Смена этапа на solution_submission")

    session: AsyncSession = await anext(get_session())

    try:
        result = await session.execute(
            select(Stage).where(Stage.is_active == True)
        )
        current_stage = result.scalar_one_or_none()

        if current_stage:
            result = await session.execute(
                select(Stage).where(Stage.type == StageType.SOLUTION_SUBMISSION.value)
            )
            solution_submission_stage = result.scalar_one_or_none()

            if solution_submission_stage:
                await session.execute(
                    update(Stage)
                    .where(Stage.id == current_stage.id)
                    .values(is_active=False)
                )

                solution_submission_stage.is_active = True

                await session.commit()
                logging.info("Этап успешно изменен на solution_submission")

                await send_solution_submission_notification(session)
            else:
                logging.error("Этап solution_submission не найден в базе данных")
        else:
            logging.warning("Активный этап не найден")
    except Exception as e:
        logging.error(f"Ошибки при изменении этапа: {str(e)}")
        await session.rollback()
        raise
    finally:
        await session.close()


async def check_and_start_solution_review():
    """
    Меняет stage на solution_review (5 этап) и отправляет уведомления
    """
    logging.info("Смена этапа на solution_review")

    session: AsyncSession = await anext(get_session())

    try:
        result = await session.execute(
            select(Stage).where(Stage.is_active == True)
        )
        current_stage = result.scalar_one_or_none()

        if current_stage:
            result = await session.execute(
                select(Stage).where(Stage.type == StageType.SOLUTION_REVIEW.value)
            )
            solution_review_stage = result.scalar_one_or_none()

            if solution_review_stage:
                await session.execute(
                    update(Stage)
                    .where(Stage.id == current_stage.id)
                    .values(is_active=False)
                )

                solution_review_stage.is_active = True

                await session.commit()
                logging.info("Этап успешно изменен на solution_review")

                await send_hackathon_ended_notification(session)
            else:
                logging.error("Этап solution_review не найден в базе данных")
        else:
            logging.warning("Активный этап не найден")
    except Exception as e:
        logging.error(f"Ошибки при изменении этапа: {str(e)}")
        await session.rollback()
        raise
    finally:
        await session.close()


async def check_time_and_start_solution_submission():
    """
    Проверяет время и меняет этап на solution_submission, если наступила целевая дата
    """
    current_date = datetime.now(tz)
    logging.info(
        f"Проверка времени для этапа solution_submission. Текущее: {current_date}, Цель: {solution_submission_date}")

    if current_date >= solution_submission_date:
        logging.info(f"Целевая дата {solution_submission_date} достигнута. Выполняю смену этапа.")
        await check_and_start_solution_submission()
        scheduler.remove_job('check_solution_submission_time')
        logging.info("Задача смены этапа на solution_submission выполнена и удалена из планировщика")
    else:
        next_minute = current_date.replace(second=0, microsecond=0) + timedelta(minutes=1)
        delay = (next_minute - current_date).total_seconds()

        if delay > 0:
            scheduler.reschedule_job(
                'check_solution_submission_time',
                trigger=IntervalTrigger(minutes=1),
                next_run_time=next_minute
            )


async def check_time_and_start_solution_review():
    """
    Проверяет время и меняет этап на solution_review, если наступила целевая дата
    """
    current_date = datetime.now(tz)
    logging.info(f"Проверка времени для этапа solution_review. Текущее: {current_date}, Цель: {solution_review_date}")

    if current_date >= solution_review_date:
        logging.info(f"Целевая дата {solution_review_date} достигнута. Выполняю смену этапа.")
        await check_and_start_solution_review()
        scheduler.remove_job('check_solution_review_time')
        logging.info("Задача смены этапа на solution_review выполнена и удалена из планировщика")
    else:
        next_minute = current_date.replace(second=0, microsecond=0) + timedelta(minutes=1)
        delay = (next_minute - current_date).total_seconds()

        if delay > 0:
            scheduler.reschedule_job(
                'check_solution_review_time',
                trigger=IntervalTrigger(minutes=1),
                next_run_time=next_minute
            )


initial_check_date = datetime.now(tz)
next_minute = initial_check_date.replace(second=0, microsecond=0) + timedelta(minutes=1)

# scheduler.add_job(
#     check_time_and_start_hackathon,
#     trigger=IntervalTrigger(minutes=1),
#     id='check_hackathon_start_time',
#     name='Check hackathon start time and switch stage',
#     next_run_time=next_minute,
#     replace_existing=True
# )
#
# scheduler.add_job(
#     check_time_and_start_solution_submission,
#     trigger=IntervalTrigger(minutes=1),
#     id='check_solution_submission_time',
#     name='Check solution submission time and switch stage',
#     next_run_time=next_minute,
#     replace_existing=True
# )
#
# scheduler.add_job(
#     check_time_and_start_solution_review,
#     trigger=IntervalTrigger(minutes=1),
#     id='check_solution_review_time',
#     name='Check solution review time and switch stage',
#     next_run_time=next_minute,
#     replace_existing=True
# )

logging.info(
    f"Scheduled hackathon start check job. Целевая дата: {hackathon_start_date}, первая проверка в {next_minute}")
logging.info(f"Scheduled solution submission check job. Целевая дата: {solution_submission_date}")
logging.info(f"Scheduled solution review check job. Целевая дата: {solution_review_date}")
