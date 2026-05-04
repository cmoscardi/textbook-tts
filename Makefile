prod-logs-%:
	docker compose -f docker-compose.prod.yml logs $*

prod-status:
	docker compose -f docker-compose.prod.yml ps --format "table {{.Service}}\t{{.Status}}"

dev-status:
	docker compose -f docker-compose.yml ps --format "table {{.Service}}\t{{.Status}}"
