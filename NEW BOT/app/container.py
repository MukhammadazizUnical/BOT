from app.services.broadcast_processor_service import BroadcastProcessorService
from app.services.broadcast_queue_service import BroadcastQueueService
from app.services.scheduler_service import SchedulerService
from app.services.userbot_service import UserbotService


userbot_service = UserbotService()
queue_service = BroadcastQueueService()
scheduler_service = SchedulerService(queue_service)
processor_service = BroadcastProcessorService(userbot_service, queue_service)
