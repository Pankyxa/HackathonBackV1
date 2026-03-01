"""
Скрипт для автоматического создания 20 команд и подтверждения всех участников
Использование: python scripts/create_test_teams.py
"""
import asyncio
import uuid
import sys
import os
from pathlib import Path

# Добавляем корневую директорию проекта в sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from src.models import User, Team, TeamMember, ParticipantInfo, User2Roles, UserStatusHistory
from src.models.enums import UserStatus, UserRole, TeamRole, TeamMemberStatus
from src.models.user import MentorInfo, UserEventStatus
from src.auth.utils import get_password_hash
from src.settings import settings
from src.utils.router_states import user_router_state, team_router_state
from src.utils.event_utils import get_active_event
from src.utils.enum_utils import get_enum_data


async def create_test_teams():
    """Создание 20 тестовых команд с участниками"""
    # Подключение к БД
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        # Инициализация enum_data
        from src.utils.enum_utils import initialize_enum_data
        await initialize_enum_data(session)
        
        # Инициализация router states
        await user_router_state.initialize(session)
        await team_router_state.initialize(session)
        
        # Получаем активное событие
        try:
            active_event = await get_active_event(session)
            print(f"✓ Активное событие: {active_event.name} (ID: {active_event.id})")
        except Exception as e:
            print(f"✗ Ошибка получения активного события: {e}")
            return
        
        # Получаем статусы и роли через enum_utils
        enum_data = get_enum_data()
        approved_status_id = enum_data.get_user_status_id(UserStatus.APPROVED)
        pending_status_id = enum_data.get_user_status_id(UserStatus.PENDING)
        participant_role_id = enum_data.get_user_role_id(UserRole.PARTICIPANT)
        teamlead_role_id = enum_data.get_team_role_id(TeamRole.TEAMLEAD)
        member_role_id = enum_data.get_team_role_id(TeamRole.MEMBER)
        mentor_role_id = enum_data.get_team_role_id(TeamRole.MENTOR)
        accepted_status_id = enum_data.get_team_member_status_id(TeamMemberStatus.ACCEPTED)
        pending_member_status_id = enum_data.get_team_member_status_id(TeamMemberStatus.PENDING)
        
        print(f"✓ Статусы и роли загружены")
        
        teams_created = 0
        users_created = 0
        unconfirmed_user_email = None  # Email пользователя, который будет неподтвержден

        # Гарантируем, что один конкретный пользователь всегда имеет статус pending
        # даже если команды уже существуют и мы их не пересоздаем.
        special_unconfirmed_email = "member1_1@test.com"
        existing_special_user_query = select(User).where(User.email == special_unconfirmed_email)
        result = await session.execute(existing_special_user_query)
        special_user = result.scalar_one_or_none()

        if special_user:
            # Обновляем статус пользователя на pending
            special_user.current_status_id = pending_status_id
            status_history = UserStatusHistory(
                id=uuid.uuid4(),
                user_id=special_user.id,
                status_id=pending_status_id,
                comment="Статус изменен на неподтвержденный для тестирования (скрипт create_test_teams)"
            )
            session.add(status_history)
            
            # Обновляем или создаем UserEventStatus для активного события
            existing_event_status_query = select(UserEventStatus).where(
                UserEventStatus.user_id == special_user.id,
                UserEventStatus.event_id == active_event.id
            )
            result = await session.execute(existing_event_status_query)
            existing_event_status = result.scalar_one_or_none()
            
            if existing_event_status:
                existing_event_status.status_id = pending_status_id
                existing_event_status.updated_at = datetime.now(timezone.utc)
            else:
                user_event_status = UserEventStatus(
                    id=uuid.uuid4(),
                    user_id=special_user.id,
                    event_id=active_event.id,
                    status_id=pending_status_id
                )
                session.add(user_event_status)
            
            unconfirmed_user_email = special_unconfirmed_email
            print(f"⚠ Пользователь {special_unconfirmed_email} найден, статус принудительно установлен в pending")

            # Если уже существует команда 1 в активном событии — приводим её запись участника к pending
            team1_query = select(Team).where(
                Team.team_name == "Команда 1",
                Team.event_id == active_event.id,
            )
            result = await session.execute(team1_query)
            team1 = result.scalar_one_or_none()

            if team1:
                tm_query = select(TeamMember).where(
                    TeamMember.team_id == team1.id,
                    TeamMember.user_id == special_user.id,
                )
                result = await session.execute(tm_query)
                tm = result.scalar_one_or_none()

                if tm:
                    tm.status_id = pending_member_status_id
                    print("  → Статус участника в команде 1 обновлен на pending")
                else:
                    team_member = TeamMember(
                        id=uuid.uuid4(),
                        team_id=team1.id,
                        user_id=special_user.id,
                        role_id=member_role_id,
                        status_id=pending_member_status_id,
                    )
                    session.add(team_member)
                    print("  → Пользователь добавлен в состав команды 1 как pending")
            
            # Коммитим изменения статуса пользователя и TeamMember сразу
            await session.commit()
            await session.refresh(special_user)
            print(f"  ✓ Изменения статуса пользователя {special_unconfirmed_email} сохранены в БД")

        # Создаем 20 команд
        for team_num in range(1, 21):
            print(f"\n--- Создание команды {team_num}/20 ---")

            # Проверяем, существует ли уже команда с таким именем в активном событии
            existing_team_query = select(Team).where(
                Team.team_name == f"Команда {team_num}",
                Team.event_id == active_event.id,
            )
            result = await session.execute(existing_team_query)
            existing_team = result.scalar_one_or_none()

            if existing_team:
                print(
                    f"  → Команда 'Команда {team_num}' уже существует в активном ивенте, пропускаю создание"
                )
                continue
            
            # Создаем тимлида
            teamlead_email = f"teamlead{team_num}@test.com"
            teamlead_name = f"Тимлид Команды {team_num}"
            
            # Проверяем, существует ли уже пользователь
            existing_user_query = select(User).where(User.email == teamlead_email)
            result = await session.execute(existing_user_query)
            teamlead_user = result.scalar_one_or_none()
            
            if not teamlead_user:
                teamlead_user = User(
                    id=uuid.uuid4(),
                    email=teamlead_email,
                    password=get_password_hash("password123"),
                    full_name=teamlead_name,
                    current_status_id=approved_status_id,
                    email_verified=True
                )
                session.add(teamlead_user)
                await session.flush()
                
                # Добавляем роль participant
                user2role = User2Roles(
                    id=uuid.uuid4(),
                    user_id=teamlead_user.id,
                    role_id=participant_role_id
                )
                session.add(user2role)
                
                # Создаем participant_info
                participant_info = ParticipantInfo(
                    id=uuid.uuid4(),
                    user_id=teamlead_user.id,
                    number=f"+790012345{team_num:02d}",
                    vuz="Тестовый ВУЗ",
                    vuz_direction="Тестовое направление",
                    code_speciality="01.01.01",
                    course="3"
                )
                session.add(participant_info)
                
                # Создаем историю статусов
                status_history = UserStatusHistory(
                    id=uuid.uuid4(),
                    user_id=teamlead_user.id,
                    status_id=approved_status_id,
                    comment="Автоматически создан для тестирования"
                )
                session.add(status_history)
                
                # Создаем UserEventStatus для активного события
                user_event_status = UserEventStatus(
                    id=uuid.uuid4(),
                    user_id=teamlead_user.id,
                    event_id=active_event.id,
                    status_id=approved_status_id
                )
                session.add(user_event_status)
                
                users_created += 1
                print(f"  ✓ Создан тимлид: {teamlead_email}")
            else:
                print(f"  → Тимлид уже существует: {teamlead_email}")
            
            # Создаем команду (без логотипа, так как это файл)
            team = Team(
                id=uuid.uuid4(),
                team_name=f"Команда {team_num}",
                team_motto=f"Девиз команды {team_num}",
                team_leader_id=teamlead_user.id,
                event_id=active_event.id,
                logo_file_id=None  # Логотип не создаем в скрипте
            )
            session.add(team)
            await session.flush()
            
            # Добавляем тимлида в команду
            teamlead_member = TeamMember(
                id=uuid.uuid4(),
                team_id=team.id,
                user_id=teamlead_user.id,
                role_id=teamlead_role_id,
                status_id=accepted_status_id
            )
            session.add(teamlead_member)
            
            # Создаем 4 участника для команды
            member_users = []
            for member_num in range(1, 5):
                member_email = f"member{team_num}_{member_num}@test.com"
                member_name = f"Участник {member_num} Команды {team_num}"
                
                # Определяем, будет ли этот пользователь неподтвержден (только первый участник первой команды)
                is_unconfirmed = (team_num == 1 and member_num == 1)
                if is_unconfirmed:
                    unconfirmed_user_email = member_email
                
                # Проверяем, существует ли уже пользователь
                existing_member_query = select(User).where(User.email == member_email)
                result = await session.execute(existing_member_query)
                member_user = result.scalar_one_or_none()
                
                # Определяем статус пользователя
                user_status_id = pending_status_id if is_unconfirmed else approved_status_id
                member_status_id = pending_member_status_id if is_unconfirmed else accepted_status_id
                
                if not member_user:
                    member_user = User(
                        id=uuid.uuid4(),
                        email=member_email,
                        password=get_password_hash("password123"),
                        full_name=member_name,
                        current_status_id=user_status_id,
                        email_verified=True
                    )
                    session.add(member_user)
                    await session.flush()
                    
                    # Добавляем роль participant
                    user2role = User2Roles(
                        id=uuid.uuid4(),
                        user_id=member_user.id,
                        role_id=participant_role_id
                    )
                    session.add(user2role)
                    
                    # Создаем participant_info
                    participant_info = ParticipantInfo(
                        id=uuid.uuid4(),
                        user_id=member_user.id,
                        number=f"+790012345{team_num:02d}{member_num}",
                        vuz="Тестовый ВУЗ",
                        vuz_direction="Тестовое направление",
                        code_speciality="01.01.01",
                        course="3"
                    )
                    session.add(participant_info)
                    
                    # Создаем историю статусов
                    status_history = UserStatusHistory(
                        id=uuid.uuid4(),
                        user_id=member_user.id,
                        status_id=user_status_id,
                        comment="Автоматически создан для тестирования"
                    )
                    session.add(status_history)
                    
                    # Создаем UserEventStatus для активного события
                    user_event_status = UserEventStatus(
                        id=uuid.uuid4(),
                        user_id=member_user.id,
                        event_id=active_event.id,
                        status_id=user_status_id
                    )
                    session.add(user_event_status)
                    
                    users_created += 1
                else:
                    # Если пользователь уже существует, обновляем его статус на неподтвержденный
                    if is_unconfirmed:
                        member_user.current_status_id = pending_status_id
                        # Обновляем историю статусов
                        new_status_history = UserStatusHistory(
                            id=uuid.uuid4(),
                            user_id=member_user.id,
                            status_id=pending_status_id,
                            comment="Статус изменен на неподтвержденный для тестирования"
                        )
                        session.add(new_status_history)
                        
                        # Обновляем или создаем UserEventStatus для активного события
                        existing_event_status_query = select(UserEventStatus).where(
                            UserEventStatus.user_id == member_user.id,
                            UserEventStatus.event_id == active_event.id
                        )
                        result = await session.execute(existing_event_status_query)
                        existing_event_status = result.scalar_one_or_none()
                        
                        if existing_event_status:
                            existing_event_status.status_id = pending_status_id
                            existing_event_status.updated_at = datetime.now(timezone.utc)
                        else:
                            user_event_status = UserEventStatus(
                                id=uuid.uuid4(),
                                user_id=member_user.id,
                                event_id=active_event.id,
                                status_id=pending_status_id
                            )
                            session.add(user_event_status)
                        
                        print(f"  → Статус пользователя {member_email} изменен на неподтвержденный")
                
                member_users.append(member_user)
                
                # Добавляем участника в команду
                # Проверяем, существует ли уже запись TeamMember для этого пользователя в этой команде
                existing_team_member_query = select(TeamMember).where(
                    TeamMember.team_id == team.id,
                    TeamMember.user_id == member_user.id
                )
                result = await session.execute(existing_team_member_query)
                existing_team_member = result.scalar_one_or_none()
                
                if existing_team_member:
                    # Обновляем статус существующего участника команды
                    existing_team_member.status_id = member_status_id
                else:
                    # Создаем нового участника команды
                    team_member = TeamMember(
                        id=uuid.uuid4(),
                        team_id=team.id,
                        user_id=member_user.id,
                        role_id=member_role_id,
                        status_id=member_status_id
                    )
                    session.add(team_member)
            
            # Создаем наставника (может быть общим для нескольких команд)
            mentor_num = (team_num - 1) % 5 + 1  # 5 наставников на 20 команд
            mentor_email = f"mentor{mentor_num}@test.com"
            mentor_name = f"Наставник {mentor_num}"
            
            # Проверяем, существует ли уже наставник
            existing_mentor_query = select(User).where(User.email == mentor_email)
            result = await session.execute(existing_mentor_query)
            mentor_user = result.scalar_one_or_none()
            
            if not mentor_user:
                mentor_user = User(
                    id=uuid.uuid4(),
                    email=mentor_email,
                    password=get_password_hash("password123"),
                    full_name=mentor_name,
                    current_status_id=approved_status_id,
                    email_verified=True
                )
                session.add(mentor_user)
                await session.flush()
                
                # Добавляем роль mentor (UserRole.MENTOR)
                mentor_user_role_id = enum_data.get_user_role_id(UserRole.MENTOR)
                user2role = User2Roles(
                    id=uuid.uuid4(),
                    user_id=mentor_user.id,
                    role_id=mentor_user_role_id
                )
                session.add(user2role)
                
                # Создаем mentor_info
                mentor_info = MentorInfo(
                    id=uuid.uuid4(),
                    user_id=mentor_user.id,
                    number=f"+790099900{mentor_num:02d}",
                    job="Тестовое место работы",
                    job_title="Тестовая должность"
                )
                session.add(mentor_info)
                
                # Создаем историю статусов
                status_history = UserStatusHistory(
                    id=uuid.uuid4(),
                    user_id=mentor_user.id,
                    status_id=approved_status_id,
                    comment="Автоматически создан для тестирования"
                )
                session.add(status_history)
                
                # Создаем UserEventStatus для активного события
                user_event_status = UserEventStatus(
                    id=uuid.uuid4(),
                    user_id=mentor_user.id,
                    event_id=active_event.id,
                    status_id=approved_status_id
                )
                session.add(user_event_status)
                
                users_created += 1
                print(f"  ✓ Создан наставник: {mentor_email}")
            
            # Добавляем наставника в команду (если ещё не добавлен)
            existing_mentor_member_query = select(TeamMember).where(
                TeamMember.team_id == team.id,
                TeamMember.user_id == mentor_user.id,
            )
            result = await session.execute(existing_mentor_member_query)
            existing_mentor_member = result.scalar_one_or_none()

            if existing_mentor_member:
                existing_mentor_member.status_id = accepted_status_id
            else:
                mentor_member = TeamMember(
                    id=uuid.uuid4(),
                    team_id=team.id,
                    user_id=mentor_user.id,
                    role_id=mentor_role_id,
                    status_id=accepted_status_id
                )
                session.add(mentor_member)
            
            await session.commit()
            teams_created += 1
            print(f"  ✓ Команда '{team.team_name}' создана успешно")
            print(f"    - Тимлид: {teamlead_email}")
            print(f"    - Участников: 4")
            print(f"    - Наставник: {mentor_email}")
        
        print(f"\n{'='*60}")
        print(f"✓ Создано команд: {teams_created}/20")
        print(f"✓ Создано пользователей: {users_created}")
        if unconfirmed_user_email:
            print(f"⚠ Неподтвержденный пользователь: {unconfirmed_user_email}")
        print(f"{'='*60}")
        print("\nВсе команды имеют статус 'active' (тимлид + 4 участника + наставник)")
        if unconfirmed_user_email:
            print(f"⚠ Один пользователь ({unconfirmed_user_email}) имеет статус 'pending' (неподтвержден)")
        print("Пароль для всех пользователей: password123")


if __name__ == "__main__":
    asyncio.run(create_test_teams())
