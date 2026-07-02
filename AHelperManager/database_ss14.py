import asyncpg
import json
from dataConfig import DATABASE_MRP, DATABASE_DEV, DATABASE_HOST, DATABASE_PORT, DATABASE_USER, DATABASE_PASS, DATABASE_MRP_SPONSOR
from datetime import datetime

class DatabaseManagerSS14:
    """
    Класс для работы в бд ВП сс14
    """
    def __init__(self):
        self.db_params = {
            'mrp': {
                'database': DATABASE_MRP,
                'user': DATABASE_USER,
                'password': DATABASE_PASS,
                'host': DATABASE_HOST,
                'port': DATABASE_PORT
            },
            'dev': {
                'database': DATABASE_DEV,
                'user': DATABASE_USER,
                'password': DATABASE_PASS,
                'host': DATABASE_HOST,
                'port': DATABASE_PORT
            },
            'mrp_sponsor': {
                'database': DATABASE_MRP_SPONSOR,
                'user': DATABASE_USER,
                'password': DATABASE_PASS,
                'host': DATABASE_HOST,
                'port': DATABASE_PORT
            }
        }

    async def get_connection(self, db_name='mrp'):
        """Возвращает асинхронное соединение с указанной базой данных"""
        if db_name not in self.db_params:
            raise ValueError(f"Неизвестное имя БД: {db_name}")

        params = self.db_params[db_name]
        dsn = f"postgres://{params['user']}:{params['password']}@{params['host']}:{params['port']}/{params['database']}"
        return await asyncpg.connect(dsn)

    async def get_admin_name(self, guid: str, db_name: str = 'mrp'):
        """
        Получает имя администратора по GUID.
        """
        conn = await self.get_connection(db_name)
        try:
            result = await conn.fetchval("SELECT last_seen_user_name FROM player WHERE user_id = $1", guid)
            return result if result else None
        finally:
            await conn.close()

    async def get_player_guid(self, nickname: str, db_name: str = 'mrp'):
        """
        Получает GUID игрока по имени.
        """
        conn = await self.get_connection(db_name)
        try:
            result = await conn.fetchval("SELECT user_id FROM player WHERE last_seen_user_name = $1", nickname)
            return result if result else None
        finally:
            await conn.close()

    async def get_player_guid_by_discord_id(self, ds_id: str, db_name: str = 'mrp'):
        """
        Получает GUID игрока по ID дискорда.
        """
        conn = await self.get_connection(db_name)
        try:
            result = await conn.fetchval("SELECT user_id FROM discord_user WHERE discord_id = $1", ds_id)
            return result if result else None
        finally:
            await conn.close()
    
    async def get_discord_info_by_guid(self, user_id: str, db_name: str = 'mrp'):
        """
        Получает discord id по GUID пользователя.
        """
        conn = await self.get_connection(db_name)
        try:
            result = await conn.fetchval("SELECT discord_id FROM discord_user WHERE user_id = $1", user_id)
            return result
        finally:
            await conn.close()

    async def get_player_name(self, guid: str, db_name: str = 'mrp'):
        """
        Получает имя игрока по GUID.
        """
        conn = await self.get_connection(db_name)
        try:
            result = await conn.fetchval("SELECT last_seen_user_name FROM player WHERE user_id = $1", guid)
            return result if result else None
        finally:
            await conn.close()

    async def search_ban_player(self, username: str, db_name: str = 'mrp'):
        """
        Получает историю банов игрока по нику.
        """
        conn = await self.get_connection(db_name)
        try:
            result = await conn.fetch("""
                SELECT 
                b.ban_id,
                b.ban_time,
                b.expiration_time,
                b.reason,
                COALESCE(p.last_seen_user_name, 'Неизвестно') AS admin_nickname,
                u.unban_time,
                COALESCE(p2.last_seen_user_name, 'Неизвестно') AS unban_admin_nickname
            FROM ban b
            INNER JOIN ban_player bp ON b.ban_id = bp.ban_id
            LEFT JOIN player p ON b.banning_admin = p.user_id
            LEFT JOIN unban u ON b.ban_id = u.ban_id
            LEFT JOIN player p2 ON u.unbanning_admin = p2.user_id
            WHERE bp.user_id = (
                SELECT user_id FROM player WHERE last_seen_user_name = $1
            )
            AND b.type = 0
            ORDER BY b.ban_id ASC
            """, username)
            return result
        except Exception as e:
            print(f"Ошибка БД: {e}")
            return None
        finally:
            await conn.close()

    async def search_notes_player(self, username: str, db_name: str = 'mrp'):
        """
        Получает заметки игрока по нику.
        """
        conn = await self.get_connection(db_name)
        try:
            result = await conn.fetch("""
                SELECT 
                    admin_notes.admin_notes_id,
                    admin_notes.created_at,
                    admin_notes.message,
                    admin_notes.severity,
                    admin_notes.secret,
                    admin_notes.last_edited_at,
                    admin_notes.last_edited_by_id,
                    player.player_id,
                    player.last_seen_user_name,
                    admin.created_by_name
                FROM admin_notes
                INNER JOIN player ON admin_notes.player_user_id = player.user_id
                LEFT JOIN (
                    SELECT user_id AS created_by_id, last_seen_user_name AS created_by_name
                    FROM player
                ) AS admin ON admin_notes.created_by_id = admin.created_by_id
                WHERE player.last_seen_user_name = $1
            """, username)
            return result
        except Exception as e:
            print(f"Ошибка БД: {e}")
            return None
        finally:
            await conn.close()

    async def unban_player(self, ban_id: int, admin_guid: str, unban_time, db_name: str = 'mrp'):
        conn = await self.get_connection(db_name)
        try:
            async with conn.transaction():
                exists = await conn.fetchval("SELECT 1 FROM ban WHERE ban_id = $1 AND type = 0", ban_id)
                if not exists:
                    return False, f"❌ Бан {ban_id} не существует."

                already_unbanned = await conn.fetchval("SELECT 1 FROM unban WHERE ban_id = $1", ban_id)
                if already_unbanned:
                    return False, f"⚠️ Бан {ban_id} уже снят."

                admin_name = await self.get_admin_name(admin_guid, db_name)
                if not admin_name:
                    return False, f"❌ При попытке найти имя админа в БД произошла ошибка: Админ с GUID {admin_guid} не найден."

                await conn.execute("""
                    INSERT INTO unban (ban_id, unbanning_admin, unban_time)
                    VALUES ($1, $2, $3::timestamptz)
                """, ban_id, admin_guid, unban_time)

                return True, f"✅ Бан {ban_id} снят админом {admin_name}."
        except Exception as e:
            return False, f"Ошибка: {e}"
        finally:
            await conn.close()
    
    async def get_admin_permission(self, nickname: str, db_name: str = 'mrp'):
        conn = await self.get_connection(db_name)
        try:
            result = await conn.fetchrow("""
                SELECT a.title, ar.name
                FROM admin a
                JOIN admin_rank ar ON a.admin_rank_id = ar.admin_rank_id
                JOIN player p ON a.user_id = p.user_id
                WHERE p.last_seen_user_name ILIKE $1
            """, nickname)
            return result
        finally:
            await conn.close()

    async def get_all_player_info(self, user_name: str, db_name: str = 'mrp'):
        conn = await self.get_connection(db_name)
        try:
            result = await conn.fetchrow("""
                SELECT player_id, user_id, first_seen_time, last_seen_user_name, last_seen_time, last_seen_address, last_seen_hwid
                FROM player
                WHERE last_seen_user_name = $1
            """, user_name)

            if result:
                last_seen_address = result['last_seen_address']
                last_seen_hwid = result['last_seen_hwid']
                related = await conn.fetch("""
                    SELECT last_seen_user_name, last_seen_address, last_seen_hwid, last_seen_time
                    FROM player
                    WHERE last_seen_address = $1 OR last_seen_hwid = $2
                """, last_seen_address, last_seen_hwid)
            else:
                related = []

            return result, related
        finally:
            await conn.close()

    async def add_permission_admin(self, guid: str, username: str, title: str, permission: str, db_name: str = 'mrp'):
        conn = await self.get_connection(db_name)
        try:
            async with conn.transaction():

                rank_id = await conn.fetchval("SELECT admin_rank_id FROM admin_rank WHERE name ILIKE $1", permission)
                if not rank_id:
                    return False, f"Не найден ранг с названием {permission}"

                await conn.execute("""
                    INSERT INTO admin (user_id, title, admin_rank_id)
                    VALUES ($1, $2, $3)
                """, guid, title, rank_id)

                return True, f"Права были успешно добавлены для {username} в БД {db_name.upper()}"

        except Exception as e:
            return False, f"Ошибка: {e}"
        finally:
            await conn.close()

    async def del_permission_admin(self, guid: str, username: str, db_name: str = 'mrp'):
        conn = await self.get_connection(db_name)
        try:
            async with conn.transaction():

                await conn.execute("""
                    DELETE FROM admin WHERE user_id = $1""", guid)

                return True, f"Права были успешно сняты для {username} в БД {db_name.upper()}"

        except Exception as e:
            return False, f"Ошибка: {e}"
        finally:
            await conn.close()
        
    async def tweak_permission_admin(self, guid: str, username: str, title: str, permission: str, db_name: str = 'mrp'):
        conn = await self.get_connection(db_name)
        try:
            async with conn.transaction():

                rank_id = await conn.fetchval("SELECT admin_rank_id FROM admin_rank WHERE name ILIKE $1", permission)
                if not rank_id:
                    return False, f"Не найден ранг с названием {permission}"

                await conn.execute("""
                    UPDATE admin SET title = $1, admin_rank_id = $2 WHERE user_id = $3
                """, title, rank_id, guid)

                return True, f"Права были успешно изменены для {username} в БД {db_name.upper()}"
        except Exception as e:
            return False, f"Ошибка: {e}"
        finally:
            await conn.close()

    async def is_linked(self, discord_id: str, db_name: str = 'mrp'):
        conn = await self.get_connection(db_name)
        try:
            result = await conn.fetchval("SELECT 1 FROM discord_user WHERE discord_id = $1", discord_id)
            return bool(result)
        finally:
            await conn.close()

    async def link_user(self, guid: str, discord_id: str, db_name: str = 'mrp'):
        conn = await self.get_connection(db_name)
        try:
            async with conn.transaction():
                max_id = await conn.fetchval("SELECT COALESCE(MAX(discord_user_id), 0) FROM discord_user") or 0
                next_id = max_id + 1
                await conn.execute("INSERT INTO discord_user (discord_user_id, user_id, discord_id) VALUES ($1, $2, $3)", next_id, guid, discord_id)
                return True, "Аккаунт привязан."
        except Exception as e:
            return False, f"Ошибка: {e}"
        finally:
            await conn.close()

    async def unlink_user(self, discord_id: str, db_name: str = 'mrp') -> tuple[bool, str]:
        conn = await self.get_connection(db_name)
        try:
            async with conn.transaction():
                result = await conn.fetchval("DELETE FROM discord_user WHERE discord_id = $1 RETURNING user_id", discord_id)
                if result:
                    return True, "Аккаунт отвязан."
                return False, "Ошибка удаления."
        except Exception as e:
            return False, f"Ошибка: {e}"
        finally:
            await conn.close()

    async def get_logs_by_round(self, username: str, round_id: int, db_name: str = 'mrp'):
        conn = await self.get_connection(db_name)
        try:
            keywords = ["used placement system to create", "Дебаг", "Админ", "was respawned", "Трюки", "Покарать"]

            like_username = f"%{username}%"
            or_conditions = " OR ".join(f"message ILIKE '%{kw}%'" for kw in keywords)
            query = f"SELECT message FROM admin_log WHERE round_id = $1 AND message ILIKE $2 AND ({or_conditions})"
            
            results = await conn.fetch(query, round_id, like_username)
            return results
        finally:
            await conn.close()

    async def get_list_permission(self, db_name: str = 'mrp'):
        conn = await self.get_connection(db_name)
        try:
            result = await conn.fetch("SELECT name FROM admin_rank ORDER BY admin_rank_id ASC")
            return result
        finally:
            await conn.close()
    
    async def get_sponsor(self, guid: str, db_name: str = 'mrp_sponsor'):
        conn = await self.get_connection(db_name)
        try:
            result = await conn.fetchrow("SELECT user_id, player_name, donate_name, tier, ooccolor, have_priority_join, extra_slots, expire_date, allow_job FROM sponsors WHERE user_id = $1", guid)
            return dict(result) if result else None
        except Exception as e:
            print(f"Ошибка БД: {e}")
            return None
        finally:
            await conn.close()

    async def delete_sponsor(self, guid: str, db_name: str = 'mrp_sponsor'):
        """Удаляет спонсора"""
        conn = await self.get_connection(db_name)
        try:
            async with conn.transaction():
                result = await conn.execute("DELETE FROM sponsors WHERE user_id = $1", guid)
                deleted = not result.endswith(" 0")
                return deleted, ("ok" if deleted else "not_found")
        except Exception as e:
            return False, f"Ошибка БД: {e}"
        finally:
            await conn.close()

    async def add_sponsor(self, guid: str, player_name: str, donate_name: str, tier: int, ooccolor: str, have_priority_join: bool, markings: list, extra_slots: int, expire_date: datetime, allow_job: bool, db_name: str = 'mrp_sponsor'):
        """
        Добавляет спонсора. Возвращает (ok: bool, info: str):
          (True, 'ok') - запись создана
          (False, 'exists') - спонсор уже есть, сначала нужно удалить
          (False, 'Ошибка БД:') - ошибка вставки
        """
        conn = await self.get_connection(db_name)
        try:
            async with conn.transaction():
                if await conn.fetchval("SELECT 1 FROM sponsors WHERE user_id = $1", guid):
                    return False, "exists"

                markings_list = list(markings) if markings else []
                markings_udt = await conn.fetchval("""
                    SELECT udt_name FROM information_schema.columns
                    WHERE table_name = 'sponsors' AND column_name = 'allowed_markings'
                """)
                markings_param = json.dumps(markings_list) if markings_udt in ('jsonb', 'json') else markings_list

                await conn.execute("""
                    INSERT INTO sponsors (user_id, player_name, donate_name, tier, ooccolor, have_priority_join, allowed_markings, extra_slots, expire_date, allow_job)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::timestamptz, $10)
                """, guid, player_name, donate_name, tier, ooccolor, have_priority_join, markings_param, extra_slots, expire_date, allow_job)
                return True, "ok"
        except Exception as e:
            return False, f"Ошибка БД: {e}"
        finally:
            await conn.close()