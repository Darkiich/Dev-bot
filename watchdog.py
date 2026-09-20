"""
Запросы к вотчдогу игровых серверов: обновление и рестарт
"""

import logging

import aiohttp

from dataConfig import POST_USER_AGENT, WATCHDOG_SERVERS

logger = logging.getLogger(__name__)

TIMEOUT = aiohttp.ClientTimeout(total=30)
BODY_LIMIT = 300

ACTIONS = {
    "update": "Обновление",
    "restart": "Рестарт",
}

SERVERS_TEXT = " или ".join(f"`{name}`" for name in WATCHDOG_SERVERS)


def known(server: str) -> bool:
    return (server or "").strip().lower() in WATCHDOG_SERVERS


async def request(server: str, action: str) -> tuple:
    """Дёргает вотчдог. Возвращает (успех, готовый текст для чата)."""
    config = WATCHDOG_SERVERS.get((server or "").strip().lower())
    if config is None:
        return False, f"❌ Неверный сервер. Доступны: {SERVERS_TEXT}"

    instance = config["instance"]
    name = ACTIONS.get(action, action)

    if not config["password"]:
        logger.error("Нет пароля вотчдога для %s", instance)
        return False, f"❌ В .env не задан `{config['env']}`, запрос не отправлен."

    url = f"http://{config['address']}:{config['port']}/instances/{instance}/{action}"
    headers = {"User-Agent": POST_USER_AGENT} if POST_USER_AGENT else {}

    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                url,
                auth=aiohttp.BasicAuth(instance, config["password"]),
                headers=headers,
            ) as resp:
                body = (await resp.text())[:BODY_LIMIT].strip()

                if resp.status == 200:
                    logger.info("%s %s: вотчдог принял запрос", name, instance)
                    return True, f"✅ {name} {instance}: вотчдог принял запрос."

                logger.error("%s %s: код %s, ответ %r", name, instance, resp.status, body)

                if resp.status in (401, 403):
                    return False, (
                        f"❌ {instance}: вотчдог не принял пароль (код {resp.status}).\n"
                        f"Проверь `{config['env']}` в .env - похоже, пароль инстанса меняли."
                    )

                tail = f"\n```{body}```" if body else ""
                return False, f"❌ {name} {instance} не выполнено, код {resp.status}.{tail}"

    except aiohttp.ClientError as e:
        logger.error("%s %s: вотчдог недоступен: %s", name, instance, e)
        return False, f"❌ {instance} не отвечает: {type(e).__name__}"
    except TimeoutError:
        logger.error("%s %s: вотчдог не ответил за %s с", name, instance, TIMEOUT.total)
        return False, f"❌ {instance} не ответил за {int(TIMEOUT.total)} секунд."
