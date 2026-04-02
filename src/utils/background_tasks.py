import logging
from datetime import datetime, timedelta
from typing import List
import asyncio
from uuid import UUID

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
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


async def send_email_async(
    *, to_email: str, subject: str, body: str, is_html: bool = True
) -> bool:
    """
    Обертка над email_sender.send_email, выполняющая отправку письма в отдельном потоке.
    Это позволяет не блокировать event‑loop FastAPI при синхронной работе SMTP‑клиента.
    """
    return await asyncio.to_thread(
        email_sender.send_email,
        to_email=to_email,
        subject=subject,
        body=body,
        is_html=is_html,
    )


# Флаг для предотвращения одновременного запуска нескольких рассылок
_team_confirmation_email_running = False


async def send_team_confirmation_email(session: AsyncSession):
    """
    Отправляет уведомления о подтверждении участия командам активного события
    """
    global _team_confirmation_email_running

    # Проверяем, не выполняется ли уже рассылка
    if _team_confirmation_email_running:
        logging.warning(
            "Рассылка уведомлений о подтверждении участия уже выполняется, пропускаем"
        )
        return

    from src.utils.event_utils import get_active_event

    try:
        active_event = await get_active_event(session)
    except Exception:
        logging.warning(
            "Активное событие не найдено, пропускаем рассылку подтверждений"
        )
        return

    # Проверяем текущий этап - рассылка должна выполняться только при переходе с REGISTRATION на REGISTRATION_CLOSED
    # Если этап уже не REGISTRATION, значит рассылка уже была выполнена
    current_stage_query = select(Stage).where(
        Stage.is_active == True, Stage.event_id == active_event.id
    )
    current_stage_result = await session.execute(current_stage_query)
    current_stage = current_stage_result.scalar_one_or_none()

    if current_stage and current_stage.type != StageType.REGISTRATION.value:
        logging.info(
            f"Текущий этап: {current_stage.type}, рассылка о подтверждении участия уже была выполнена, пропускаем"
        )
        return

    # Устанавливаем флаг выполнения
    _team_confirmation_email_running = True

    try:
        teams_query = (
            select(Team)
            .where(Team.event_id == active_event.id)
            .options(
                selectinload(Team.members)
                .selectinload(TeamMember.user)
                .selectinload(User.current_status),
                selectinload(Team.members).selectinload(TeamMember.role),
                selectinload(Team.members).selectinload(TeamMember.status),
            )
        )
        result = await session.execute(teams_query)
        teams = result.scalars().all()

        active_teams = [team for team in teams if team.get_status() == "active"]
        total_teams = len(active_teams)
        successful_sends = 0
        failed_sends = 0
        processed_user_ids = set()  # чтобы один пользователь не получил несколько писем

        logging.info(
            f"Начало рассылки уведомлений о подтверждении участия. Всего команд: {total_teams}"
        )
        start_time = datetime.now()

        for i, team in enumerate(active_teams, 1):
            team_members = [
                member.user
                for member in team.members
                if member.status_id == team_router_state.accepted_status_id
            ]

            for member in team_members:
                # Пропускаем, если этому пользователю уже отправляли письмо
                if not member.email or member.id in processed_user_ids:
                    continue
                processed_user_ids.add(member.id)

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
                                                            <p style="margin: 0;">Здравствуйте, {
                    member.full_name
                }!</p>
                                                        </td>
                                                    </tr>
                                                    <tr>
                                                        <td align="center" style="padding: 0 0 20px 0;">
                                                            <p style="margin: 0;">Ваша команда "{
                    team.team_name
                }" успешно зарегистрирована для участия в хакатоне.</p>
                                                        </td>
                                                    </tr>
                                                    <tr>
                                                        <td align="center" style="padding: 0 0 20px 0;">
                                                            <p style="margin: 0;">Состав команды:</p>
                                                            <ul style="list-style: none; padding: 0;">
                                                                {
                    "".join(
                        [
                            f'<li style="margin: 5px 0;">{tm.user.full_name} ({tm.role.name})</li>'
                            for tm in team.members
                            if tm.status_id == team_router_state.accepted_status_id
                        ]
                    )
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
                    success = await send_email_async(
                        to_email=member.email,
                        subject="Подтверждение участия в хакатоне",
                        body=html_content,
                        is_html=True,
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

                # Небольшая пауза, чтобы не DDOS-ить SMTP, но не блокировать сервер надолго
                await asyncio.sleep(0.1)

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        logging.info(f"""
Рассылка уведомлений о подтверждении участия завершена!
Время выполнения: {duration:.2f} секунд
Всего команд: {total_teams}
Успешно отправлено: {successful_sends}
Ошибок отправки: {failed_sends}
    """)
    except Exception as e:
        logging.error(
            f"Ошибка при выполнении рассылки уведомлений о подтверждении участия: {str(e)}"
        )
    finally:
        # Сбрасываем флаг выполнения в любом случае
        _team_confirmation_email_running = False


async def send_team_confirmation_email_background():
    """
    Обертка для отправки уведомлений о подтверждении участия в фоновом режиме.
    Создает собственную сессию БД, чтобы не зависеть от сессии HTTP‑запроса.
    """
    session: AsyncSession = await anext(get_session())
    try:
        await send_team_confirmation_email(session)
    finally:
        await session.close()


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
                                            <td align="center" style="padding: 0 0 10px 0;">
                                                <p style="margin: 0; color: #64748b; font-size: 14px;">
                                                    Или перейдите по ссылке: <a href="{settings.base_url}/profile" style="color: #2196F3; word-break: break-all;">{settings.base_url}/profile</a>
                                                </p>
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

    await send_email_async(
        to_email=user.email,
        subject="Приглашение в команду",
        body=html_content,
        is_html=True,
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
    <body style="margin: 0; padding: 0; background-color: #f1f5f9; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;">
        <table border="0" cellpadding="0" cellspacing="0" width="100%">
            <tr>
                <td align="center" style="padding: 40px 15px;">
                    <table border="0" cellpadding="0" cellspacing="0" width="600" style="background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
                        <tr>
                            <td style="background-color: #1e3a8a; padding: 20px 30px;">
                                <span style="color: #ffffff; font-size: 20px; font-weight: 600;">i university</span>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding: 40px 30px;">
                                <h1 style="margin: 0 0 20px 0; color: #0f172a; font-size: 24px; font-weight: 700;">Подтверждение регистрации</h1>
                                <p style="margin: 0 0 15px 0; color: #334155; font-size: 16px; line-height: 1.6;">
                                    Здравствуйте, <strong>{user.full_name}</strong>!
                                </p>
                                <p style="margin: 0 0 30px 0; color: #334155; font-size: 16px; line-height: 1.6;">
                                    Благодарим за регистрацию. Для подтверждения вашего email адреса и активации аккаунта, пожалуйста, нажмите на кнопку ниже:
                                </p>
                                <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-bottom: 30px;">
                                    <tr>
                                        <td align="center">
                                            <a href="{confirmation_link}" style="background-color: #2563eb; color: #ffffff; padding: 14px 32px; text-decoration: none; border-radius: 8px; font-weight: 600; display: inline-block; font-size: 16px; box-shadow: 0 2px 4px rgba(37, 99, 235, 0.2);">
                                                Подтвердить email
                                            </a>
                                        </td>
                                    </tr>
                                </table>
                                <p style="margin: 0; color: #64748b; font-size: 14px;">
                                    Или перейдите по ссылке: <br>
                                    <a href="{confirmation_link}" style="color: #2563eb; word-break: break-all;">{confirmation_link}</a>
                                </p>
                            </td>
                        </tr>
                        <tr>
                            <td style="background-color: #f8fafc; padding: 20px 30px; border-top: 1px solid #e2e8f0; text-align: center;">
                                <p style="margin: 0; color: #94a3b8; font-size: 13px;">
                                    Если вы не регистрировались на нашем сайте, просто проигнорируйте это письмо.
                                </p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """

    await send_email_async(
        to_email=user.email,
        subject="Подтверждение регистрации",
        body=html_content,
        is_html=True,
    )


async def send_status_change_email(user: User, new_status: str, comment: str = None):
    """Отправляет email с уведомлением об изменении статуса пользователя"""

    status_descriptions = {
        "pending": "на рассмотрении",
        "approved": "одобрен",
        "need_update": "требует обновления",
        "PENDING": "на рассмотрении",
        "APPROVED": "одобрен",
        "NEED_UPDATE": "требует обновления",
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
    <body style="margin: 0; padding: 0; background-color: #f1f5f9; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;">
        <table border="0" cellpadding="0" cellspacing="0" width="100%">
            <tr>
                <td align="center" style="padding: 40px 15px;">
                    <table border="0" cellpadding="0" cellspacing="0" width="600" style="background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
                        <tr>
                            <td style="background-color: #1e3a8a; padding: 20px 30px;">
                                <span style="color: #ffffff; font-size: 20px; font-weight: 600;">i university</span>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding: 40px 30px;">
                                <h1 style="margin: 0 0 20px 0; color: #0f172a; font-size: 24px; font-weight: 700;">Изменение статуса</h1>
                                <p style="margin: 0 0 15px 0; color: #334155; font-size: 16px; line-height: 1.6;">
                                    Здравствуйте, <strong>{user.full_name}</strong>!
                                </p>
                                <p style="margin: 0 0 15px 0; color: #334155; font-size: 16px; line-height: 1.6;">
                                    Ваш статус участника был изменен на: <strong style="color: #2563eb;">"{status_text}"</strong>.
                                </p>
                                
                                {comment_block}

                                <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 30px;">
                                    <tr>
                                        <td align="center">
                                            <a href="{settings.base_url}/profile" style="background-color: #2563eb; color: #ffffff; padding: 14px 32px; text-decoration: none; border-radius: 8px; font-weight: 600; display: inline-block; font-size: 16px; box-shadow: 0 2px 4px rgba(37, 99, 235, 0.2);">
                                                Перейти в личный кабинет
                                            </a>
                                        </td>
                                    </tr>
                                </table>
                                <p style="margin: 10px 0 0 0; color: #64748b; font-size: 14px; text-align: center;">
                                    Или перейдите по ссылке: <a href="{settings.base_url}/profile" style="color: #2563eb; word-break: break-all;">{settings.base_url}/profile</a>
                                </p>
                            </td>
                        </tr>
                        <tr>
                            <td style="background-color: #f8fafc; padding: 20px 30px; border-top: 1px solid #e2e8f0; text-align: center;">
                                <p style="margin: 0; color: #94a3b8; font-size: 13px;">
                                    Это автоматическое уведомление, пожалуйста, не отвечайте на него.
                                </p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """

    await send_email_async(
        to_email=user.email,
        subject="Изменение статуса участника",
        body=html_content,
        is_html=True,
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
            User2Roles.role_id.in_(
                [
                    user_router_state.participant_role_id,
                    user_router_state.mentor_role_id,
                ]
            )
        )
    )

    result = await session.execute(users_query)
    users = result.scalars().all()

    total_users = len(users)
    successful_sends = 0
    failed_sends = 0

    logging.info(
        f"Начало рассылки уведомлений об открытии хакатона. Всего получателей: {total_users}"
    )
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
                                                    <p style="margin: 0; color: #64748b; font-size: 14px;">
                                                        Или перейдите по ссылке: <a href="https://bigbb2.tyuiu.ru/b/hyc-sjb-5lk-prq" style="color: #2196F3; word-break: break-all;">https://bigbb2.tyuiu.ru/b/hyc-sjb-5lk-prq</a>
                                                    </p>
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
            success = await send_email_async(
                to_email=user.email,
                subject="Консультация хакатона",
                body=html_content,
                is_html=True,
            )
            if success:
                successful_sends += 1
                logging.info(
                    f"[{i}/{total_users}] Отправлено уведомление на email: {user.email}"
                )
            else:
                failed_sends += 1
                logging.error(
                    f"[{i}/{total_users}] Ошибка отправки на email: {user.email}"
                )
        except Exception as e:
            failed_sends += 1
            logging.error(
                f"[{i}/{total_users}] Исключение при отправке на email {user.email}: {str(e)}"
            )

        if i < total_users:
            await asyncio.sleep(0.1)

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
        success = await send_email_async(
            to_email=user.email,
            subject="Консультация хакатона",
            body=html_content,
            is_html=True,
        )
        if success:
            logging.info(
                f"Отправлено уведомление о консультации на email: {user.email}"
            )
        else:
            logging.error(
                f"Ошибка отправки уведомления о консультации на email: {user.email}"
            )
        return success
    except Exception as e:
        logging.error(
            f"Исключение при отправке уведомления о консультации на email {user.email}: {str(e)}"
        )
        return False


async def send_judge_briefing_notification(session: AsyncSession):
    """
    Фоновая задача для рассылки уведомлений о брифинге
    всем членам жюри активного события с задержкой между отправками
    """
    from src.models.event import EventJudge
    from src.utils.event_utils import get_active_event

    # Получаем активное событие
    active_event = await get_active_event(session)

    # Получаем жюри, привязанные к активному событию
    users_query = (
        select(User)
        .distinct()
        .join(EventJudge, User.id == EventJudge.judge_id)
        .where(EventJudge.event_id == active_event.id)
    )

    result = await session.execute(users_query)
    users = result.scalars().all()

    total_users = len(users)
    successful_sends = 0
    failed_sends = 0

    logging.info(
        f"Начало рассылки уведомлений о брифинге. Всего получателей: {total_users}"
    )
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
            success = await send_email_async(
                to_email=user.email,
                subject="Брифинг для членов жюри хакатона",
                body=html_content,
                is_html=True,
            )
            if success:
                successful_sends += 1
                logging.info(
                    f"[{i}/{total_users}] Отправлено уведомление на email: {user.email}"
                )
            else:
                failed_sends += 1
                logging.error(
                    f"[{i}/{total_users}] Ошибка отправки на email: {user.email}"
                )
        except Exception as e:
            failed_sends += 1
            logging.error(
                f"[{i}/{total_users}] Исключение при отправке на email {user.email}: {str(e)}"
            )

        if i < total_users:
            await asyncio.sleep(0.1)

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
        success = await send_email_async(
            to_email=user.email,
            subject="Брифинг для членов жюри хакатона",
            body=html_content,
            is_html=True,
        )
        if success:
            logging.info(f"Отправлено уведомление о брифинге на email: {user.email}")
        else:
            logging.error(
                f"Ошибка отправки уведомления о брифинге на email: {user.email}"
            )
        return success
    except Exception as e:
        logging.error(
            f"Исключение при отправке уведомления о брифинге на email {user.email}: {str(e)}"
        )
        return False


async def send_registration_closed_notification(session: AsyncSession):
    """
    Отправляет уведомление о закрытии регистрации и публикации исходных данных
    всем активным командам активного события
    """
    from src.utils.event_utils import get_active_event

    try:
        active_event = await get_active_event(session)
    except Exception:
        logging.warning(
            "Активное событие не найдено, пропускаем рассылку о закрытии регистрации"
        )
        return

    teams_query = (
        select(Team)
        .where(Team.event_id == active_event.id)
        .options(
            joinedload(Team.members).joinedload(TeamMember.status),
            joinedload(Team.members).joinedload(TeamMember.role),
            joinedload(Team.members)
            .joinedload(TeamMember.user)
            .joinedload(User.current_status),
        )
    )

    result = await session.execute(teams_query)
    all_teams = result.unique().scalars().all()

    active_teams = [team for team in all_teams if team.get_status() == "active"]

    total_teams = len(active_teams)
    successful_sends = 0
    failed_sends = 0
    processed_user_ids = set()  # чтобы один пользователь (например, наставник в нескольких командах) не получил несколько писем

    logging.info(
        f"Начало рассылки уведомлений о закрытии регистрации. Всего активных команд: {total_teams}"
    )
    start_time = datetime.now()

    for i, team in enumerate(active_teams, 1):
        team_members = team.get_active_members()

        for member in team_members:
            # Пропускаем, если этому пользователю уже отправляли письмо
            if not member.user.email or member.user.id in processed_user_ids:
                continue
            processed_user_ids.add(member.user.id)

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
                                                        <h1 style="color: #2196F3; font-size: 24px; margin: 0;">Ваша команда участвует в хакатоне</h1>
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
                                                        <p style="margin: 0;">Поздравляем! Ваша команда успешно зарегистрирована и участвует в хакатоне. В разделе "Моя команда" доступны материалы и актуальная информация для дальнейшей работы.</p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 20px 0;">
                                                        <table border="0" cellpadding="0" cellspacing="0">
                                                            <tr>
                                                                <td align="center" bgcolor="#2196F3" style="border-radius: 4px;">
                                                                    <a href="{settings.base_url}/profile/team" 
                                                                       style="display: inline-block; padding: 12px 24px; color: #ffffff; text-decoration: none; font-weight: bold;">
                                                                        Перейти в раздел "Моя команда"
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
                success = await send_email_async(
                    to_email=member.user.email,
                    subject="Ваша команда участвует в хакатоне",
                    body=html_content,
                    is_html=True,
                )
                if success:
                    successful_sends += 1
                    logging.info(
                        f"[Команда {i}/{total_teams}] Отправлено уведомление участнику {member.user.full_name} ({member.user.email})"
                    )
                else:
                    failed_sends += 1
                    logging.error(
                        f"[Команда {i}/{total_teams}] Ошибка отправки участнику {member.user.full_name} ({member.user.email})"
                    )
            except Exception as e:
                failed_sends += 1
                logging.error(
                    f"[Команда {i}/{total_teams}] Исключение при отправке участнику {member.user.full_name} ({member.user.email}): {str(e)}"
                )

            await asyncio.sleep(0.1)

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
    всем участникам активных команд активного события
    """
    from src.utils.event_utils import get_active_event

    try:
        active_event = await get_active_event(session)
    except Exception:
        logging.warning(
            "Активное событие не найдено, пропускаем рассылку о дополнении к исходным данным"
        )
        return

    logging.info("Начинаю рассылку уведомлений о дополнении к исходным данным")
    start_time = datetime.now()

    teams_query = (
        select(Team)
        .where(Team.event_id == active_event.id)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members).selectinload(TeamMember.role),
            selectinload(Team.members).selectinload(TeamMember.status),
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
            member
            for member in team.members
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
                success = await send_email_async(
                    to_email=member.user.email,
                    subject="Опубликовано дополнение к исходным данным",
                    body=html_content,
                    is_html=True,
                )
                if success:
                    successful_sends += 1
                    logging.info(
                        f"[Команда {i}/{total_teams}] Отправлено уведомление участнику {member.user.full_name} ({member.user.email})"
                    )
                else:
                    failed_sends += 1
                    logging.error(
                        f"[Команда {i}/{total_teams}] Ошибка отправки участнику {member.user.full_name} ({member.user.email})"
                    )
            except Exception as e:
                failed_sends += 1
                logging.error(
                    f"[Команда {i}/{total_teams}] Исключение при отправке участнику {member.user.full_name} ({member.user.email}): {str(e)}"
                )

            await asyncio.sleep(0.1)

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
    Отправляет уведомление об открытии хакатона всем участникам активных команд активного события
    """
    from src.utils.event_utils import get_active_event

    try:
        active_event = await get_active_event(session)
    except Exception:
        logging.warning(
            "Активное событие не найдено, пропускаем рассылку об открытии хакатона"
        )
        return

    teams_query = (
        select(Team)
        .where(Team.event_id == active_event.id)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members).selectinload(TeamMember.role),
            selectinload(Team.members).selectinload(TeamMember.status),
        )
    )
    result = await session.execute(teams_query)
    teams = result.scalars().all()

    active_teams = [team for team in teams if team.get_status() == "active"]
    total_teams = len(active_teams)
    successful_sends = 0
    failed_sends = 0

    logging.info(
        f"Начало рассылки уведомлений об открытии хакатона. Всего команд: {total_teams}"
    )
    start_time = datetime.now()

    for i, team in enumerate(active_teams, 1):
        logging.info(f"Обработка команды {i}/{total_teams}: {team.team_name}")

        team_members = [
            member.user
            for member in team.members
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
                                                        <p style="margin: 0;">Приглашаем вас на открытие Хакатона, которое состоится <strong>01.04.2026 в 09:00 (МСК)</strong>. Подключиться к трансляции можно по ссылке ниже.</p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 20px 0;">
                                                        <table border="0" cellpadding="0" cellspacing="0">
                                                            <tr>
                                                                <td align="center" bgcolor="#2196F3" style="border-radius: 4px;">
                                                                    <a href="https://bigbb2.tyuiu.ru/b/zah-tka-oxi-n4i" 
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
                                                        <p style="margin: 0;">Или перейдите по ссылке: <a href="https://bigbb2.tyuiu.ru/b/zah-tka-oxi-n4i" style="color: #2196F3;">https://bigbb2.tyuiu.ru/b/zah-tka-oxi-n4i</a></p>
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
                success = await send_email_async(
                    to_email=member.email,
                    subject="Открытие хакатона",
                    body=html_content,
                    is_html=True,
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

            await asyncio.sleep(0.1)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    logging.info(f"""
Рассылка уведомлений об открытии хакатона завершена!
Время выполнения: {duration:.2f} секунд
Всего команд: {total_teams}
Успешно отправлено: {successful_sends}
Ошибок отправки: {failed_sends}
    """)


KICKOFF_MEETING_EXTRA_RECIPIENTS = ["kbelozerov1@gmail.com"]


def build_kickoff_meeting_email_html(
    full_name: str, team_name: str | None = None
) -> str:
    team_name_block = ""
    if team_name:
        team_name_block = f"""
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Команда: {team_name}</p>
                                                    </td>
                                                </tr>
        """

    return f"""
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
                                                        <h1 style="color: #2196F3; font-size: 24px; margin: 0;">Установочная встреча Хакатона</h1>
                                                    </td>
                                                </tr>
                                            </table>

                                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Здравствуйте, {full_name}!</p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Приглашаем вас на установочную встречу с участниками Хакатона, которая состоится <strong>27.03.2026 в 13:00 (МСК)</strong>.</p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Подключиться к установочной встрече можно по ссылке ниже.</p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 20px 0;">
                                                        <table border="0" cellpadding="0" cellspacing="0">
                                                            <tr>
                                                                <td align="center" bgcolor="#2196F3" style="border-radius: 4px;">
                                                                    <a href="https://bigbb2.tyuiu.ru/b/zah-tka-oxi-n4i"
                                                                       style="display: inline-block; padding: 12px 24px; color: #ffffff; text-decoration: none; font-weight: bold;">
                                                                        Подключиться к встрече
                                                                    </a>
                                                                </td>
                                                            </tr>
                                                        </table>
                                                    </td>
                                                </tr>
{team_name_block}
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


async def send_kickoff_meeting_notification_to_extra_recipients():
    successful_sends = 0
    failed_sends = 0

    for recipient_email in KICKOFF_MEETING_EXTRA_RECIPIENTS:
        try:
            success = await send_email_async(
                to_email=recipient_email,
                subject="Установочная встреча Хакатона - 27.03.2026 в 13:00 (МСК)",
                body=build_kickoff_meeting_email_html("коллеги"),
                is_html=True,
            )
            if success:
                successful_sends += 1
                logging.info(
                    f"Отправлено дополнительное уведомление об установочной встрече на {recipient_email}"
                )
            else:
                failed_sends += 1
                logging.error(
                    f"Ошибка отправки дополнительного уведомления об установочной встрече на {recipient_email}"
                )
        except Exception as e:
            failed_sends += 1
            logging.error(
                f"Исключение при отправке дополнительного уведомления об установочной встрече на {recipient_email}: {str(e)}"
            )

    return successful_sends, failed_sends


async def send_kickoff_meeting_notification(session: AsyncSession):
    """
    Отправляет уведомление об установочной встрече всем участникам активных команд активного события
    """
    from src.utils.event_utils import get_active_event

    try:
        active_event = await get_active_event(session)
    except Exception:
        logging.warning(
            "Активное событие не найдено, пропускаем рассылку об установочной встрече"
        )
        return

    teams_query = (
        select(Team)
        .where(Team.event_id == active_event.id)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members).selectinload(TeamMember.role),
            selectinload(Team.members).selectinload(TeamMember.status),
        )
    )
    result = await session.execute(teams_query)
    teams = result.scalars().all()

    active_teams = [team for team in teams if team.get_status() == "active"]
    total_teams = len(active_teams)
    successful_sends = 0
    failed_sends = 0

    logging.info(
        f"Начало рассылки уведомлений об установочной встрече. Всего команд: {total_teams}"
    )
    start_time = datetime.now()

    for i, team in enumerate(active_teams, 1):
        logging.info(f"Обработка команды {i}/{total_teams}: {team.team_name}")

        team_members = [
            member.user
            for member in team.members
            if member.status_id == team_router_state.accepted_status_id
            and member.role_id
            in [
                team_router_state.teamlead_role_id,
                team_router_state.member_role_id,
            ]
        ]

        for member in team_members:
            html_content = build_kickoff_meeting_email_html(
                member.full_name, team.team_name
            )

            try:
                success = await send_email_async(
                    to_email=member.email,
                    subject="Установочная встреча Хакатона - 27.03.2026 в 13:00 (МСК)",
                    body=html_content,
                    is_html=True,
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

            await asyncio.sleep(0.1)

    (
        extra_successful_sends,
        extra_failed_sends,
    ) = await send_kickoff_meeting_notification_to_extra_recipients()
    successful_sends += extra_successful_sends
    failed_sends += extra_failed_sends

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    logging.info(f"""
Рассылка уведомлений об установочной встрече завершена!
Время выполнения: {duration:.2f} секунд
Всего команд: {total_teams}
Успешно отправлено: {successful_sends}
Ошибок отправки: {failed_sends}
    """)


async def send_hackathon_started_notification(session: AsyncSession):
    """
    Отправляет уведомление о начале хакатона и публикации тестовых данных
    всем активным командам активного события
    """
    from src.utils.event_utils import get_active_event

    try:
        active_event = await get_active_event(session)
    except Exception:
        logging.warning(
            "Активное событие не найдено, пропускаем рассылку о старте хакатона"
        )
        return

    teams_query = (
        select(Team)
        .where(Team.event_id == active_event.id)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members).selectinload(TeamMember.role),
            selectinload(Team.members).selectinload(TeamMember.status),
        )
    )
    result = await session.execute(teams_query)
    teams = result.scalars().all()

    active_teams = [team for team in teams if team.get_status() == "active"]
    total_teams = len(active_teams)
    successful_sends = 0
    failed_sends = 0

    logging.info(
        f"Начало рассылки уведомлений о старте хакатона. Всего команд: {total_teams}"
    )
    start_time = datetime.now()

    for i, team in enumerate(active_teams, 1):
        team_members = [
            member.user
            for member in team.members
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
                success = await send_email_async(
                    to_email=member.email,
                    subject="Хакатон начался! Опубликованы тестовые данные",
                    body=html_content,
                    is_html=True,
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

            await asyncio.sleep(0.1)

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
    всем активным командам активного события
    """
    from src.utils.event_utils import get_active_event

    try:
        active_event = await get_active_event(session)
    except Exception:
        logging.warning(
            "Активное событие не найдено, пропускаем рассылку о завершении хакатона"
        )
        return

    teams_query = (
        select(Team)
        .where(Team.event_id == active_event.id)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members).selectinload(TeamMember.role),
            selectinload(Team.members).selectinload(TeamMember.status),
        )
    )
    result = await session.execute(teams_query)
    teams = result.scalars().all()

    active_teams = [team for team in teams if team.get_status() == "active"]
    total_teams = len(active_teams)
    successful_sends = 0
    failed_sends = 0

    logging.info(
        f"Начало рассылки уведомлений о завершении хакатона. Всего команд: {total_teams}"
    )
    start_time = datetime.now()

    for i, team in enumerate(active_teams, 1):
        team_members = [
            member.user
            for member in team.members
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
                success = await send_email_async(
                    to_email=member.email,
                    subject="Завершение хакатона через 30 минут",
                    body=html_content,
                    is_html=True,
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

            await asyncio.sleep(0.1)

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
    всем активным командам активного события
    """
    from src.utils.event_utils import get_active_event

    try:
        active_event = await get_active_event(session)
    except Exception:
        logging.warning(
            "Активное событие не найдено, пропускаем рассылку об окончании хакатона"
        )
        return

    teams_query = (
        select(Team)
        .where(Team.event_id == active_event.id)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members).selectinload(TeamMember.role),
            selectinload(Team.members).selectinload(TeamMember.status),
        )
    )
    result = await session.execute(teams_query)
    teams = result.scalars().all()

    active_teams = [team for team in teams if team.get_status() == "active"]
    total_teams = len(active_teams)
    successful_sends = 0
    failed_sends = 0

    logging.info(
        f"Начало рассылки уведомлений об окончании хакатона. Всего команд: {total_teams}"
    )
    start_time = datetime.now()

    for i, team in enumerate(active_teams, 1):
        team_members = [
            member.user
            for member in team.members
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
                success = await send_email_async(
                    to_email=member.email,
                    subject="Хакатон завершен",
                    body=html_content,
                    is_html=True,
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
Рассылка уведомлений об окончании хакатона завершена!
Время выполнения: {duration:.2f} секунд
Всего команд: {total_teams}
Успешно отправлено: {successful_sends}
Ошибок отправки: {failed_sends}
""")


async def send_judge_opening_notification(session: AsyncSession):
    """
    Отправляет уведомление об очном открытии хакатона всем членам жюри активного события
    """
    from src.models.event import EventJudge
    from src.utils.event_utils import get_active_event

    # Получаем активное событие
    active_event = await get_active_event(session)

    # Получаем жюри, привязанные к активному событию
    users_query = (
        select(User)
        .distinct()
        .join(EventJudge, User.id == EventJudge.judge_id)
        .where(EventJudge.event_id == active_event.id)
    )

    result = await session.execute(users_query)
    users = result.scalars().all()

    total_users = len(users)
    successful_sends = 0
    failed_sends = 0

    logging.info(
        f"Начало рассылки уведомлений об очном открытии хакатона членам жюри. Всего получателей: {total_users}"
    )
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
            success = await send_email_async(
                to_email=user.email,
                subject="Очное открытие хакатона",
                body=html_content,
                is_html=True,
            )
            if success:
                successful_sends += 1
                logging.info(
                    f"[{i}/{total_users}] Отправлено уведомление на email: {user.email}"
                )
            else:
                failed_sends += 1
                logging.error(
                    f"[{i}/{total_users}] Ошибка отправки на email: {user.email}"
                )
        except Exception as e:
            failed_sends += 1
            logging.error(
                f"[{i}/{total_users}] Исключение при отправке на email {user.email}: {str(e)}"
            )

        if i < total_users:
            await asyncio.sleep(0.1)

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
    всем активным командам активного события
    """
    from src.utils.event_utils import get_active_event

    try:
        active_event = await get_active_event(session)
    except Exception:
        logging.warning(
            "Активное событие не найдено, пропускаем рассылку о защите проектов"
        )
        return

    teams_query = (
        select(Team)
        .where(Team.event_id == active_event.id)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members).selectinload(TeamMember.role),
            selectinload(Team.members).selectinload(TeamMember.status),
        )
    )
    result = await session.execute(teams_query)
    teams = result.scalars().all()

    active_teams = [team for team in teams if team.get_status() == "active"]
    total_teams = len(active_teams)
    successful_sends = 0
    failed_sends = 0

    logging.info(
        f"Начало рассылки уведомлений о защите проектов. Всего команд: {total_teams}"
    )
    start_time = datetime.now()

    defense_schedule = {
        "Двойной удар": "09:00",
        "WattNot": "09:15",
        "Заземленные": "09:30",
        "Команда ЮГУ": "09:45",
        "ЭнергоТек": "10:00",
        "Шнур питания не найден": "10:15",
        "поБЕДА": "10:30",
        "исТок": "10:45",
        "МПК ТИУ": "11:30",
        "Шалуны Джоуля": "11:45",
        "Русы": "12:00",
    }

    for i, team in enumerate(active_teams, 1):
        team_members = [
            member.user
            for member in team.members
            if member.status_id == team_router_state.accepted_status_id
        ]

        team_defense_time = defense_schedule.get(team.team_name)
        defense_time_message = (
            f"Время защиты вашей команды по Москве: <strong>{team_defense_time}</strong>. "
            if team_defense_time
            else ""
        )

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
                                                        <p style="margin: 0;">Опубликован список защит проектов. {defense_time_message}В зависимости от вашего времени защиты присоединяйтесь по ссылке ниже.</p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 0 0 20px 0;">
                                                        <p style="margin: 0;">Во время защиты необходимо продемонстрировать работу своей программы. В докладе перечислите результаты моделирования.</p>
                                                        <p style="margin: 10px 0 0 0;">Список защит опубликован на главной странице сайта.</p>
                                                        <p style="margin: 10px 0 0 0;"><strong>График защит представлен на главной странице сайта.</strong></p>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td align="center" style="padding: 20px 0;">
                                                        <table border="0" cellpadding="0" cellspacing="0">
                                                            <tr>
                                                                <td align="center" bgcolor="#2196F3" style="border-radius: 4px;">
                                                                    <a href="https://bigbb2.tyuiu.ru/b/zah-tka-oxi-n4i" 
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
                success = await send_email_async(
                    to_email=member.email,
                    subject="Опубликован список защит проектов",
                    body=html_content,
                    is_html=True,
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

            await asyncio.sleep(0.1)

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
    from src.utils.event_utils import get_active_event

    try:
        active_event = await get_active_event(session)
    except Exception:
        logging.warning(
            "Активное событие не найдено, пропускаем рассылку о торжественном закрытии первого этапа"
        )
        return

    teams_query = (
        select(Team)
        .where(Team.event_id == active_event.id)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members).selectinload(TeamMember.role),
            selectinload(Team.members).selectinload(TeamMember.status),
        )
    )
    result = await session.execute(teams_query)
    teams = result.scalars().all()

    active_teams = [team for team in teams if team.get_status() == "active"]
    total_teams = len(active_teams)
    successful_sends = 0
    failed_sends = 0

    logging.info(
        f"Начало рассылки уведомлений о торжественном закрытии первого этапа. Всего команд: {total_teams}"
    )
    start_time = datetime.now()

    for i, team in enumerate(active_teams, 1):
        team_members = [
            member.user
            for member in team.members
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
                                                    <h1 style="color: #2196F3; font-size: 24px; margin: 0;">Торжественное закрытие первого этапа</h1>
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
                                                    <p style="margin: 0;">Приглашаем вас принять участие в торжественном закрытии первого этапа. В рамках церемонии будут объявлены финалисты первого этапа. Подключиться к трансляции можно по ссылке ниже.</p>
                                                </td>
                                            </tr>
                                            <tr>
                                                <td align="center" style="padding: 20px 0;">
                                                    <table border="0" cellpadding="0" cellspacing="0">
                                                        <tr>
                                                            <td align="center" bgcolor="#2196F3" style="border-radius: 4px;">
                                                                <a href="https://bigbb2.tyuiu.ru/b/zah-tka-oxi-n4i" 
                                                                   style="display: inline-block; padding: 12px 24px; color: #ffffff; text-decoration: none; font-weight: bold;">
                                                                    Присоединиться к закрытию первого этапа
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
                success = await send_email_async(
                    to_email=member.email,
                    subject="Торжественное закрытие первого этапа",
                    body=html_content,
                    is_html=True,
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
    Рассылка уведомлений о торжественном закрытии первого этапа завершена!
    Время выполнения: {duration:.2f} секунд
    Всего команд: {total_teams}
    Успешно отправлено: {successful_sends}
    Ошибок отправки: {failed_sends}
    """)


async def send_first_stage_results_notification(session: AsyncSession):
    from src.utils.event_utils import get_active_event

    try:
        active_event = await get_active_event(session)
    except Exception:
        logging.warning(
            "Активное событие не найдено, пропускаем рассылку о результатах первого этапа"
        )
        return

    teams_query = (
        select(Team)
        .where(Team.event_id == active_event.id)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members).selectinload(TeamMember.role),
            selectinload(Team.members).selectinload(TeamMember.status),
        )
    )
    result = await session.execute(teams_query)
    teams = result.scalars().all()

    active_teams = [team for team in teams if team.get_status() == "active"]
    total_teams = len(active_teams)
    successful_sends = 0
    failed_sends = 0

    logging.info(
        f"Начало рассылки уведомлений о результатах первого этапа. Всего команд: {total_teams}"
    )
    start_time = datetime.now()

    for i, team in enumerate(active_teams, 1):
        team_members = [
            member.user
            for member in team.members
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
                                                    <h1 style="color: #2196F3; font-size: 24px; margin: 0;">Первый этап завершен</h1>
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
                                                    <p style="margin: 0;">Первый этап Хакатона завершен. Если вы не участвовали в онлайн-закрытии, вы можете ознакомиться с результатами и списком финалистов на главной странице сайта.</p>
                                                </td>
                                            </tr>
                                            <tr>
                                                <td align="center" style="padding: 20px 0;">
                                                    <table border="0" cellpadding="0" cellspacing="0">
                                                        <tr>
                                                            <td align="center" bgcolor="#2196F3" style="border-radius: 4px;">
                                                                <a href="{settings.base_url}" 
                                                                   style="display: inline-block; padding: 12px 24px; color: #ffffff; text-decoration: none; font-weight: bold;">
                                                                    Перейти на главную страницу
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
                success = await send_email_async(
                    to_email=member.email,
                    subject="Результаты первого этапа Хакатона",
                    body=html_content,
                    is_html=True,
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
    Рассылка уведомлений о результатах первого этапа завершена!
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
        from src.utils.event_utils import get_active_event

        active_event = await get_active_event(session)

        result = await session.execute(
            select(Stage).where(
                Stage.is_active == True, Stage.event_id == active_event.id
            )
        )
        current_stage = result.scalar_one_or_none()

        if current_stage:
            result = await session.execute(
                select(Stage).where(
                    Stage.type == StageType.TASK_DISTRIBUTION.value,
                    Stage.event_id == active_event.id,
                )
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
        from src.utils.event_utils import get_active_event

        active_event = await get_active_event(session)

        result = await session.execute(
            select(Stage).where(
                and_(
                    Stage.is_active == True,
                    Stage.type == StageType.REGISTRATION.value,
                    Stage.event_id == active_event.id,
                )
            )
        )
        current_stage = result.scalar_one_or_none()

        if current_stage:
            result = await session.execute(
                select(Stage).where(
                    Stage.type == StageType.REGISTRATION_CLOSED.value,
                    Stage.event_id == active_event.id,
                )
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
                logging.info(
                    "Этап регистрации успешно изменен на этап регистрация закрыта"
                )

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


tz = pytz.timezone("Europe/Moscow")
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
        logging.info(
            f"Целевая дата {target_date} достигнута. Выполняю закрытие регистрации."
        )
        await check_and_close_registration()
        scheduler.remove_job("check_registration_time")
        logging.info("Задача закрытия регистрации выполнена и удалена из планировщика")
    else:
        logging.info(
            f"Целевая дата еще не достигнута. Ожидаю... Текущее время: {current_date}"
        )


async def check_time_and_start_hackathon():
    """
    Проверяет время и запускает хакатон, если наступила целевая дата.
    При первом запуске рассчитывает точное время следующей проверки.
    """
    current_date = datetime.now(tz)
    logging.info(
        f"Проверка времени для старта хакатона. Текущее: {current_date}, Цель: {hackathon_start_date}"
    )

    if current_date >= hackathon_start_date:
        logging.info(
            f"Целевая дата {hackathon_start_date} достигнута. Выполняю запуск хакатона."
        )
        await check_and_start_hackathon()
        scheduler.remove_job("check_hackathon_start_time")
        logging.info("Задача запуска хакатона выполнена и удалена из планировщика")
    else:
        # Рассчитываем время до следующей минуты
        next_minute = current_date.replace(second=0, microsecond=0) + timedelta(
            minutes=1
        )
        delay = (next_minute - current_date).total_seconds()

        if delay > 0:
            logging.info(
                f"Корректировка расписания. Следующая проверка через {delay:.2f} секунд"
            )

            # Удаляем текущее расписание
            scheduler.remove_job("check_hackathon_start_time")

            # Создаем новое расписание, начиная с следующей минуты
            # scheduler.add_job(
            #     check_time_and_start_hackathon,
            #     trigger=IntervalTrigger(minutes=1),
            #     id='check_hackathon_start_time',
            #     name='Check hackathon start time and switch stage',
            #     next_run_time=next_minute,
            #     replace_existing=True
            # )

        logging.info(
            f"Целевая дата еще не достигнута. Следующая проверка в {next_minute}"
        )


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
        from src.utils.event_utils import get_active_event

        active_event = await get_active_event(session)

        result = await session.execute(
            select(Stage).where(
                Stage.is_active == True, Stage.event_id == active_event.id
            )
        )
        current_stage = result.scalar_one_or_none()

        if current_stage:
            result = await session.execute(
                select(Stage).where(
                    Stage.type == StageType.SOLUTION_SUBMISSION.value,
                    Stage.event_id == active_event.id,
                )
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
        from src.utils.event_utils import get_active_event

        active_event = await get_active_event(session)

        result = await session.execute(
            select(Stage).where(
                Stage.is_active == True, Stage.event_id == active_event.id
            )
        )
        current_stage = result.scalar_one_or_none()

        if current_stage:
            result = await session.execute(
                select(Stage).where(
                    Stage.type == StageType.SOLUTION_SUBMISSION.value,
                    Stage.event_id == active_event.id,
                )
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
        from src.utils.event_utils import get_active_event

        active_event = await get_active_event(session)

        result = await session.execute(
            select(Stage).where(
                Stage.is_active == True, Stage.event_id == active_event.id
            )
        )
        current_stage = result.scalar_one_or_none()

        if current_stage:
            result = await session.execute(
                select(Stage).where(
                    Stage.type == StageType.SOLUTION_REVIEW.value,
                    Stage.event_id == active_event.id,
                )
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
        f"Проверка времени для этапа solution_submission. Текущее: {current_date}, Цель: {solution_submission_date}"
    )

    if current_date >= solution_submission_date:
        logging.info(
            f"Целевая дата {solution_submission_date} достигнута. Выполняю смену этапа."
        )
        await check_and_start_solution_submission()
        scheduler.remove_job("check_solution_submission_time")
        logging.info(
            "Задача смены этапа на solution_submission выполнена и удалена из планировщика"
        )
    else:
        next_minute = current_date.replace(second=0, microsecond=0) + timedelta(
            minutes=1
        )
        delay = (next_minute - current_date).total_seconds()

        if delay > 0:
            scheduler.reschedule_job(
                "check_solution_submission_time",
                trigger=IntervalTrigger(minutes=1),
                next_run_time=next_minute,
            )


async def check_time_and_start_solution_review():
    """
    Проверяет время и меняет этап на solution_review, если наступила целевая дата
    """
    current_date = datetime.now(tz)
    logging.info(
        f"Проверка времени для этапа solution_review. Текущее: {current_date}, Цель: {solution_review_date}"
    )

    if current_date >= solution_review_date:
        logging.info(
            f"Целевая дата {solution_review_date} достигнута. Выполняю смену этапа."
        )
        await check_and_start_solution_review()
        scheduler.remove_job("check_solution_review_time")
        logging.info(
            "Задача смены этапа на solution_review выполнена и удалена из планировщика"
        )
    else:
        next_minute = current_date.replace(second=0, microsecond=0) + timedelta(
            minutes=1
        )
        delay = (next_minute - current_date).total_seconds()

        if delay > 0:
            scheduler.reschedule_job(
                "check_solution_review_time",
                trigger=IntervalTrigger(minutes=1),
                next_run_time=next_minute,
            )


initial_check_date = datetime.now(tz)
next_minute = initial_check_date.replace(second=0, microsecond=0) + timedelta(minutes=1)


async def activate_stage_automatically(
    stage: Stage, session: AsyncSession, reason: str = "автоматически"
):
    """
    Универсальная функция для автоматической активации этапа
    Деактивирует текущий активный этап и активирует указанный

    Args:
        stage: Этап для активации
        session: Сессия БД
        reason: Причина активации (для логирования)
    """
    from src.utils.event_utils import get_active_event
    from src.utils.router_states import stage_router_state

    try:
        active_event = await get_active_event(session)

        if stage.event_id != active_event.id:
            logging.warning(f"Этап {stage.id} не принадлежит активному событию")
            return False

        # Получаем текущий активный этап
        current_stage_query = select(Stage).where(
            Stage.is_active == True, Stage.event_id == active_event.id
        )
        current_stage_result = await session.execute(current_stage_query)
        current_stage = current_stage_result.scalar_one_or_none()

        # Деактивируем текущий этап
        if current_stage:
            await session.execute(
                update(Stage)
                .where(Stage.id == current_stage.id)
                .values(is_active=False)
            )
            logging.info(f"Этап '{current_stage.name}' деактивирован")

        # Активируем новый этап
        stage.is_active = True
        await session.commit()
        await session.refresh(stage)

        # Обновляем состояние роутера
        await stage_router_state.initialize(session)

        logging.info(f"Этап '{stage.name}' успешно активирован {reason}")

        # Если это registration_closed, отправляем уведомления
        if stage.type == StageType.REGISTRATION_CLOSED.value:
            await send_registration_closed_notification(session)

        return True

    except Exception as e:
        logging.error(f"Ошибка при активации этапа {stage.id}: {str(e)}")
        await session.rollback()
        return False


async def activate_stage_automatically_background(
    stage_id: UUID, reason: str = "автоматически"
):
    """
    Обертка для автоматической активации этапа в фоновом режиме.
    Создает собственную сессию БД, чтобы не зависеть от сессии HTTP‑запроса.
    """
    session: AsyncSession = await anext(get_session())
    try:
        # Загружаем этап
        stage_query = select(Stage).where(Stage.id == stage_id)
        stage_result = await session.execute(stage_query)
        stage = stage_result.scalar_one_or_none()

        if not stage:
            logging.error(f"Этап {stage_id} не найден для автоматической активации")
            return

        await activate_stage_automatically(stage, session, reason)
    finally:
        await session.close()


async def auto_activate_stage(stage_id: str):
    """
    Автоматически активирует этап по расписанию (по времени)
    """
    logging.info(f"Автоматическая активация этапа {stage_id} по расписанию")
    session: AsyncSession = await anext(get_session())

    try:
        # Получаем этап
        stage_query = select(Stage).where(Stage.id == stage_id)
        stage_result = await session.execute(stage_query)
        stage = stage_result.scalar_one_or_none()

        if not stage:
            logging.error(f"Этап {stage_id} не найден")
            return

        # Проверяем, что этап еще не активирован
        if stage.is_active:
            logging.info(f"Этап {stage_id} уже активен, пропускаем активацию")
            return

        # Активируем этап
        await activate_stage_automatically(stage, session, "по расписанию")

        # Удаляем задачу из планировщика, так как этап уже активирован
        job_id = f"auto_activate_stage_{stage_id}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
            logging.info(
                f"Задача автоматической активации {job_id} удалена из планировщика"
            )

    except Exception as e:
        logging.error(f"Ошибка при автоматической активации этапа {stage_id}: {str(e)}")
        await session.rollback()
    finally:
        await session.close()


async def check_and_schedule_auto_activate_stages():
    """
    Проверяет все этапы с is_auto_activate=True и планирует их автоматическую активацию
    Вызывается при старте приложения и при создании/обновлении этапов
    """
    logging.info("=== Начало проверки этапов для автоматической активации ===")
    session: AsyncSession = await anext(get_session())

    try:
        from src.utils.event_utils import get_active_event

        try:
            active_event = await get_active_event(session)
            logging.info(f"Активное событие: {active_event.id} ({active_event.name})")
        except Exception as e:
            logging.warning(
                f"Активное событие не найдено, пропускаем планирование: {e}"
            )
            return

        # Получаем все этапы с автоматической активацией для активного события
        stages_query = (
            select(Stage)
            .where(
                Stage.event_id == active_event.id,
                Stage.is_auto_activate == True,
                Stage.auto_activate_at.isnot(None),
                Stage.is_active == False,  # Только неактивные этапы
            )
            .order_by(Stage.auto_activate_at.asc(), Stage.order.asc())
        )
        stages_result = await session.execute(stages_query)
        stages = stages_result.scalars().all()
        desired_job_ids = {f"auto_activate_stage_{stage.id}" for stage in stages}

        logging.info(f"Найдено этапов с автоматической активацией: {len(stages)}")

        current_time = datetime.now(pytz.UTC)
        logging.info(f"Текущее время (UTC): {current_time}")

        all_jobs = scheduler.get_jobs()
        auto_activate_jobs = [
            job for job in all_jobs if job.id.startswith("auto_activate_stage_")
        ]

        for job in auto_activate_jobs:
            if job.id not in desired_job_ids:
                scheduler.remove_job(job.id)
                logging.info(
                    f"Удалена устаревшая задача автоматической активации: {job.id}"
                )

        for stage in stages:
            job_id = f"auto_activate_stage_{stage.id}"

            logging.info(
                f"Этап '{stage.name}' (ID: {stage.id}): "
                f"is_auto_activate={stage.is_auto_activate}, "
                f"auto_activate_at={stage.auto_activate_at} (UTC), "
                f"is_active={stage.is_active}"
            )

            existing_job = scheduler.get_job(job_id)

            if stage.auto_activate_at.tzinfo is None:
                logging.warning(
                    f"Время активации этапа {stage.id} не имеет timezone, предполагаем UTC"
                )
                stage.auto_activate_at = pytz.UTC.localize(stage.auto_activate_at)

            # Проверяем, не прошло ли уже время активации
            time_diff = (stage.auto_activate_at - current_time).total_seconds()
            logging.info(
                f"Разница времени до активации: {time_diff} секунд ({time_diff / 60:.1f} минут)"
            )

            if stage.auto_activate_at <= current_time:
                if existing_job:
                    scheduler.remove_job(job_id)
                    logging.info(
                        f"Удалена существующая задача {job_id} перед немедленной активацией"
                    )
                logging.info(
                    f"Время активации этапа {stage.id} уже прошло, активируем немедленно"
                )
                await auto_activate_stage(str(stage.id))
            else:
                logging.info(
                    f"Планирование автоматической активации этапа '{stage.name}' (ID: {stage.id}) "
                    f"на {stage.auto_activate_at} (UTC)"
                )
                try:
                    scheduler.add_job(
                        auto_activate_stage,
                        trigger=DateTrigger(run_date=stage.auto_activate_at),
                        id=job_id,
                        name=f"Auto activate stage {stage.name}",
                        args=[str(stage.id)],
                        replace_existing=True,
                    )
                    scheduled_job = scheduler.get_job(job_id)
                    if scheduled_job:
                        logging.info(
                            f"Задача успешно запланирована. Следующий запуск: {scheduled_job.next_run_time}"
                        )
                    else:
                        logging.error(f"Задача не была добавлена в планировщик!")
                except Exception as e:
                    logging.error(f"Ошибка при добавлении задачи в планировщик: {e}")

        all_jobs = scheduler.get_jobs()
        auto_activate_jobs = [
            job for job in all_jobs if job.id.startswith("auto_activate_stage_")
        ]
        logging.info(
            f"Всего запланировано задач автоматической активации: {len(auto_activate_jobs)}"
        )
        for job in auto_activate_jobs:
            logging.info(
                f"  - {job.id}: {job.name}, следующий запуск: {job.next_run_time}"
            )

        logging.info("=== Конец проверки этапов для автоматической активации ===")

    except Exception as e:
        logging.error(
            f"Ошибка при планировании автоматической активации этапов: {str(e)}",
            exc_info=True,
        )
    finally:
        await session.close()


async def check_conditional_auto_activate_stages(session: AsyncSession):
    """
    Проверяет этапы с условиями для автоматической активации (например, registration_closed)
    """
    from src.utils.event_utils import get_active_event
    from src.utils.team_utils import check_active_teams

    try:
        active_event = await get_active_event(session)
    except Exception:
        logging.warning("Активное событие не найдено, пропускаем проверку условий")
        return

    # Проверяем registration_closed - активируется при достижении 20 активных команд
    current_stage_query = select(Stage).where(
        Stage.is_active == True, Stage.event_id == active_event.id
    )
    current_stage_result = await session.execute(current_stage_query)
    current_stage = current_stage_result.scalar_one_or_none()

    # Если текущий этап - регистрация, проверяем условие для registration_closed
    if current_stage and current_stage.type == StageType.REGISTRATION.value:
        active_teams = await check_active_teams(session)
        active_teams_count = len(active_teams)

        if active_teams_count >= 20:
            # Ищем этап registration_closed
            registration_closed_query = select(Stage).where(
                Stage.type == StageType.REGISTRATION_CLOSED.value,
                Stage.event_id == active_event.id,
                Stage.is_active == False,
            )
            registration_closed_result = await session.execute(
                registration_closed_query
            )
            registration_closed_stage = registration_closed_result.scalar_one_or_none()

            if registration_closed_stage:
                logging.info(
                    f"Условие выполнено: {active_teams_count} активных команд >= 20. "
                    f"Активируем этап '{registration_closed_stage.name}'"
                )
                await activate_stage_automatically(
                    registration_closed_stage,
                    session,
                    "при достижении лимита команд (20)",
                )


# Периодическая проверка этапов для автоматической активации (каждую минуту)
async def periodic_check_auto_activate_stages():
    """
    Периодически проверяет этапы для автоматической активации:
    1. Этапы с активацией по времени (is_auto_activate=True)
    2. Этапы с активацией по условиям (например, registration_closed)
    """
    session: AsyncSession = await anext(get_session())

    try:
        # Проверяем этапы с активацией по времени
        await check_and_schedule_auto_activate_stages()

        # Проверяем этапы с активацией по условиям
        await check_conditional_auto_activate_stages(session)
    except Exception as e:
        logging.error(
            f"Ошибка при периодической проверке автоматической активации: {str(e)}"
        )
    finally:
        await session.close()


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
    f"Scheduled hackathon start check job. Целевая дата: {hackathon_start_date}, первая проверка в {next_minute}"
)
logging.info(
    f"Scheduled solution submission check job. Целевая дата: {solution_submission_date}"
)
logging.info(
    f"Scheduled solution review check job. Целевая дата: {solution_review_date}"
)
