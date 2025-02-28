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
                }}
                .container {{
                    background-color: #ffffff;
                    border-radius: 8px;
                    padding: 30px;
                    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
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