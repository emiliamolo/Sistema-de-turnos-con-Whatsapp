import json
import logging
import time

from ..core.redis import get_redis
from .flow import process_message
from .reminders import check_and_send_reminders

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("turnos_worker")


def main():
    redis = get_redis()
    logger.info("Turnos-Worker listening on 'whatsapp_queue'...")
    last_reminder_check = time.time()
    REMINDER_INTERVAL = 300
    while True:
        try:
            result = redis.blpop("whatsapp_queue", timeout=30)
            if result:
                _, message_json = result
                data = json.loads(message_json)
                process_message(data, redis)

            now = time.time()
            if now - last_reminder_check >= REMINDER_INTERVAL:
                check_and_send_reminders(redis)
                last_reminder_check = now
        except Exception as e:
            logger.error(f"Error in worker loop: {e}")
            time.sleep(2)


if __name__ == "__main__":
    main()
