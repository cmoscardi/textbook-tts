"""
Celery configuration for ML worker

This configuration is optimized for long-running GPU tasks that can take several minutes.
"""

# Broker connection settings
broker_heartbeat = 0  # Disable heartbeat timeout for long-running tasks
broker_connection_retry_on_startup = True
broker_connection_max_retries = None  # Unlimited reconnection attempts

# Task acknowledgement settings
task_acks_late = True  # Only acknowledge task after it completes (prevents message loss if worker dies)
worker_prefetch_multiplier = 1  # Only fetch one task at a time (important for GPU tasks)

# Task time limits (10 minutes soft, 15 minutes hard)
task_soft_time_limit = 600  # Soft limit in seconds
task_time_limit = 900  # Hard limit in seconds
