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
    <html>
        <head>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    line-height: 1.6;
                    color: #333333;
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                    text-align: center; 
                }}
                .container {{
                    background-color: #ffffff;
                    border-radius: 8px;
                    padding: 30px;
                    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                    text-align: center;
                }}
                .header {{
                    text-align: center;
                    margin-bottom: 30px;
                }}
                .title {{
                    color: #2196F3;
                    font-size: 24px;
                    margin: 0;
                }}
                .team-info {{
                    background-color: #f5f5f5;
                    padding: 15px;
                    border-radius: 4px;
                    margin: 20px 0;
                }}
                .footer {{
                    font-size: 14px;
                    color: #666666;
                    margin-top: 30px;
                    text-align: center;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 class="title">Подтверждение участия в хакатоне</h1>
                </div>
                
                <p>Поздравляем! Ваша команда "{team.team_name}" успешно зарегистрирована для участия в хакатоне.</p>
                
                <div class="team-info">
                    <h3>Состав команды:</h3>
                    <p>{members_list}</p>
                </div>
                
                <p>Следите за обновлениями на нашем сайте:</p>
                <p><a href="{settings.base_url}">Хакатон "Цифровые двойники в энергетике"</a></p>
                
                <div class="footer">
                    <p>Желаем удачи в соревновании!</p>
                </div>
            </div>
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
    <html>
        <head>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    line-height: 1.6;
                    color: #333333;
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                    text-align: center; 
                }}
                .container {{
                    background-color: #ffffff;
                    border-radius: 8px;
                    padding: 30px;
                    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                    text-align: center;
                }}
                .header {{
                    text-align: center;
                    margin-bottom: 30px;
                }}
                .title {{
                    color: #2196F3;
                    font-size: 24px;
                    margin: 0;
                }}
                .button {{
                    display: inline-block;
                    background-color: #2196F3;
                    color: white;
                    text-decoration: none;
                    padding: 12px 24px;
                    border-radius: 4px;
                    margin: 20px 0;
                }}
                .footer {{
                    font-size: 14px;
                    color: #666666;
                    margin-top: 30px;
                    text-align: center;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 class="title">Приглашение в команду</h1>
                </div>

                <p>Здравствуйте, {user.full_name}!</p>

                <p>Вас приглашают присоединиться к команде "{team.team_name}".</p>

                <div style="text-align: center;">
                    <a href="{settings.base_url}/profile" class="button">Перейти в личный кабинет</a>
                </div>

                <p>В личном кабинете вы сможете принять или отклонить приглашение.</p>

                <div class="footer">
                    <p>Если вы не регистрировались на нашем сайте, просто проигнорируйте это письмо.</p>
                </div>
            </div>
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
    await asyncio.sleep(10)

    html_content = f"""
    <html>
        <head>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    line-height: 1.6;
                    color: #333333;
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                    text-align: center; 
                }}
                .container {{
                    background-color: #ffffff;
                    border-radius: 8px;
                    padding: 30px;
                    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                    text-align: center;
                }}
                .header {{
                    text-align: center;
                    margin-bottom: 30px;
                }}
                .title {{
                    color: #2196F3;
                    font-size: 24px;
                    margin: 0;
                }}
                .button {{
                    display: inline-block;
                    background-color: #2196F3;
                    color: white;
                    text-decoration: none;
                    padding: 12px 24px;
                    border-radius: 4px;
                    margin: 20px 0;
                }}
                .footer {{
                    font-size: 14px;
                    color: #666666;
                    margin-top: 30px;
                    text-align: center;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 class="title">Подтверждение регистрации</h1>
                </div>

                <p>Здравствуйте, {user.full_name}!</p>

                <p>Для завершения регистрации перейдите по ссылке:</p>

                <div style="text-align: center;">
                    <a href="{confirmation_link}" class="button">Подтвердить email</a>
                </div>

                <div class="footer">
                    <p>Если вы не регистрировались на нашем сайте, просто проигнорируйте это письмо.</p>
                </div>
            </div>
        </body>
    </html>
    """

    email_sender.send_email(
        to_email=user.email,
        subject="Подтверждение регистрации",
        body=html_content,
        is_html=True
    )
